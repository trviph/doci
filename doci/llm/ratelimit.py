"""Distributed token-bucket rate limiter for LLM calls, backed by Valkey/Redis.

The audit agents fan out many model calls in a short window and hard-fail on
provider 429s. This paces them: every call reserves its token cost from a shared
bucket sized to a tokens-per-minute budget, and **waits for refill** when the
budget is exhausted rather than firing and 429-ing.

The bucket state lives in Redis (one hash per task, ``ratelimit:llm:<task>``) so
the budget is enforced across the whole worker fleet, not per-process. The
refill+consume is a single atomic Lua script run through :meth:`KV.script`, using
the Redis server clock (``TIME``) as the one authoritative time source so worker
clock skew can't matter.

Budget (``RATE_LIMIT_TPM``) and refill window (``RATE_LIMIT_WINDOW_S``) resolve
through the standard three-level env chain
(``DOCI_LLM_<TASK>_<FIELD>`` -> ``DOCI_LLM_<FIELD>`` -> code default), and either
can be overridden per bucket/call via explicit kwargs.
"""

import asyncio
import logging
import os
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doci.kvstore.client import KV

_log = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_TPM = 500_000  # tokens per window; also the bucket capacity
DEFAULT_RATE_LIMIT_WINDOW_S = 60  # seconds to refill a full budget

# Refill (up to capacity) then consume `requested` iff available. Returns 0 when
# consumed, else the wait in ms until enough tokens accrue (without consuming).
# Uses the Redis server clock so all workers share one time source.
_ACQUIRE_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000.0

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * rate)

local wait_ms = 0
if tokens >= requested then
  tokens = tokens - requested
else
  wait_ms = math.ceil((requested - tokens) / rate * 1000.0)
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)
return wait_ms
"""

# Refill, then apply a signed delta (positive = consume more, negative = refund).
# Tokens may go negative (a call may cost more than reserved); the upper bound is
# clamped to capacity so refunds can't inflate the bucket past full.
_ADJUST_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local delta = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000.0

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * rate)
tokens = tokens - delta
if tokens > capacity then tokens = capacity end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)
return 1
"""


def _env(task: str, field: str, default: str) -> str:
    """``DOCI_LLM_<TASK>_<field>`` -> ``DOCI_LLM_<field>`` -> ``default`` (truthy chain)."""
    t = task.upper()
    return (
        os.getenv(f"DOCI_LLM_{t}_{field}")
        or os.getenv(f"DOCI_LLM_{field}")
        or default
    )


def resolve_rate_limit(
    task: str, *, tpm: int | None = None, window_s: int | None = None
) -> tuple[int, int]:
    """Resolve ``(tpm, window_s)`` for ``task``; explicit args override env/defaults."""
    if tpm is None:
        tpm = int(_env(task, "RATE_LIMIT_TPM", str(DEFAULT_RATE_LIMIT_TPM)))
    if window_s is None:
        window_s = int(_env(task, "RATE_LIMIT_WINDOW_S", str(DEFAULT_RATE_LIMIT_WINDOW_S)))
    return tpm, window_s


class RedisTokenBucket:
    """A shared token bucket (capacity ``tpm``, refilling over ``window_s``).

    Coordinated entirely in Redis, so many instances across processes pointing at
    the same ``key`` enforce one fleet-wide budget. Construct via
    :func:`build_rate_limit_middleware`; a ``tpm <= 0`` means "disabled" and is
    handled there (no bucket is built).
    """

    def __init__(
        self,
        kv: "KV",
        *,
        tpm: int,
        window_s: int,
        key: str,
        ttl_s: int | None = None,
        max_sleep_s: float = 5.0,
    ) -> None:
        self._capacity = float(tpm)
        self._rate = tpm / max(1, window_s)  # tokens/sec
        self._key = key
        # Outlive a full window of idleness so a paused bucket isn't reset to full
        # mid-wait; refills lazily on next touch anyway.
        self._ttl_s = ttl_s if ttl_s is not None else max(window_s * 2, 60)
        self._max_sleep_s = max_sleep_s
        self._acquire = kv.script(_ACQUIRE_LUA)
        self._adjust = kv.script(_ADJUST_LUA)

    async def acquire(self, tokens: int) -> None:
        """Block until ``tokens`` are available, then consume them."""
        need = max(0, int(tokens))
        if need > self._capacity:
            _log.warning(
                "rate-limit %s: request of %d tokens exceeds capacity %d; clamping",
                self._key,
                need,
                int(self._capacity),
            )
            need = int(self._capacity)
        while True:
            wait_ms = int(
                await self._acquire(
                    keys=[self._key],
                    args=[self._rate, self._capacity, need, self._ttl_s],
                )
            )
            if wait_ms <= 0:
                return
            # Jitter de-synchronizes concurrent waiters (not strictly FIFO, but it
            # avoids a thundering herd re-polling in lockstep).
            delay = min(wait_ms / 1000.0, self._max_sleep_s) + random.uniform(0, 0.05)
            await asyncio.sleep(delay)

    async def adjust(self, delta: int) -> None:
        """Reconcile actual vs reserved: debit (``+``) or refund (``-``) ``delta`` tokens."""
        if delta == 0:
            return
        await self._adjust(
            keys=[self._key],
            args=[self._rate, self._capacity, int(delta), self._ttl_s],
        )


__all__ = [
    "DEFAULT_RATE_LIMIT_TPM",
    "DEFAULT_RATE_LIMIT_WINDOW_S",
    "RedisTokenBucket",
    "resolve_rate_limit",
]
