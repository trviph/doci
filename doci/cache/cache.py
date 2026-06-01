"""Ephemeral cache with a selectable backend.

A :class:`Cache` stores small, JSON-serializable, short-lived values. Pick a
:class:`CacheMode`:

- ``KV_THEN_MEM`` — read/write the KV (Valkey/Redis); on a KV error fall back to a
  per-process in-memory store and trip a short cooldown breaker so subsequent calls
  skip the (likely still-down) KV until it self-heals.
- ``MEM_ONLY`` — per-process in-memory only (no KV), e.g. data that must NOT be shared
  across instances.

Values are written to exactly one backend per call; cross-backend/cross-instance
inconsistency is acceptable for ephemeral data. ``None`` is treated as a miss and is
never cached, so a hit is unambiguous.
"""

import time
from enum import StrEnum
from typing import Any

from cachetools import TLRUCache
from opentelemetry.trace import SpanKind, get_current_span
from redis.exceptions import RedisError

from doci.kvstore import KV
from doci.telemetry import Counter, current_report, traced, with_metrics, with_span

#: Cache operations, tagged with {backend: kv|mem, op: get|set|delete, result: hit|miss}.
CACHE_OPS = Counter("doci.cache.ops", description="Cache operations")


class CacheMode(StrEnum):
    KV_THEN_MEM = "kv_then_mem"
    MEM_ONLY = "mem_only"


def _ttu(_key: Any, value: tuple[Any, float], now: float) -> float:
    # value is (cached_value, ttl); the in-mem entry expires at now + ttl.
    return now + value[1]


@traced
class Cache:
    """Ephemeral cache over KV (with in-mem fallback) or in-mem only."""

    def __init__(
        self,
        *,
        mode: CacheMode,
        kv: KV | None = None,
        namespace: str = "",
        maxsize: int = 1024,
        default_ttl: int | None = None,
        kv_cooldown_seconds: float = 5.0,
    ) -> None:
        if mode is CacheMode.KV_THEN_MEM and kv is None:
            raise ValueError("CacheMode.KV_THEN_MEM requires a kv client")
        self._mode = mode
        self._kv = kv
        self._namespace = namespace
        self._default_ttl = default_ttl
        self._cooldown = kv_cooldown_seconds
        self._mem: TLRUCache[str, tuple[Any, float]] = TLRUCache(
            maxsize=maxsize, ttu=_ttu
        )
        self._kv_down_until = 0.0  # monotonic deadline; KV is skipped until then

    # region internals
    def _k(self, key: str) -> str:
        return f"{self._namespace}:{key}" if self._namespace else key

    def _ttl(self, ttl: int | None) -> int:
        eff = ttl if ttl is not None else self._default_ttl
        if eff is None or eff <= 0:
            raise ValueError("cache entries require a positive ttl (ephemeral)")
        return eff

    def _kv_up(self) -> bool:
        return time.monotonic() >= self._kv_down_until

    def _trip(self) -> None:
        self._kv_down_until = time.monotonic() + self._cooldown

    def _mem_get(self, k: str) -> Any | None:
        try:
            return self._mem[k][0]
        except KeyError:
            return None

    def _record(self, op: str, backend: str, result: str | None = None) -> None:
        span = get_current_span()
        span.set_attribute("cache.backend", backend)
        if result is not None:
            span.set_attribute("cache.result", result)
        attrs = {"op": op, "backend": backend}
        if result is not None:
            attrs["result"] = result
        current_report().record(CACHE_OPS, 1, **attrs)

    # endregion

    # region operations
    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def get(self, key: str) -> Any | None:
        k = self._k(key)
        if self._mode is CacheMode.KV_THEN_MEM and self._kv_up():
            try:
                value = await self._kv.get_json(k)
                self._record("get", "kv", "miss" if value is None else "hit")
                return value
            except RedisError:
                self._trip()
        value = self._mem_get(k)
        self._record("get", "mem", "miss" if value is None else "hit")
        return value

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        if value is None:  # None is a miss; never cached
            return
        eff = self._ttl(ttl)
        k = self._k(key)
        if self._mode is CacheMode.KV_THEN_MEM and self._kv_up():
            try:
                await self._kv.set_json(k, value, ttl=eff)
                self._record("set", "kv")
                return
            except RedisError:
                self._trip()
        self._mem[k] = (value, eff)
        self._record("set", "mem")

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def delete(self, key: str) -> None:
        k = self._k(key)
        # A key may live in either backend, so clear both (best-effort).
        self._mem.pop(k, None)
        if self._mode is CacheMode.KV_THEN_MEM and self._kv_up():
            try:
                await self._kv.delete(k)
            except RedisError:
                self._trip()
        self._record("delete", "mem" if self._mode is CacheMode.MEM_ONLY else "kv")

    # endregion
