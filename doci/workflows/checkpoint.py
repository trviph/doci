"""A custom LangGraph checkpointer backed by Valkey/Redis, with per-key TTL.

The official ``langgraph-checkpoint-redis`` requires the RediSearch module, which
plain Valkey does not ship. This saver implements the ``BaseCheckpointSaver``
contract over ordinary Valkey commands (HSET / SADD / EXPIRE) on its own logical
db (default db 2), and stamps a configurable TTL (default 3 days) on every key so
abandoned workflow checkpoints self-expire.

Checkpoints are stored whole (``channel_values`` inline) rather than split into
per-channel blobs: simpler, and the ``BaseCheckpointSaver`` delta-history default
works against the public contract. Async-only — the synchronous methods raise, as
the graphs are always driven via ``ainvoke``.
"""

import functools
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import ormsgpack
import redis.asyncio as aioredis
from langchain_core.runnables import RunnableConfig
from opentelemetry import context as _otel_ctx
from opentelemetry.instrumentation.utils import _SUPPRESS_INSTRUMENTATION_KEY
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

_DEFAULT_URL = "redis://localhost:6379/2"
_DEFAULT_TTL = 3 * 24 * 60 * 60  # 3 days, in seconds
_DEFAULT_PREFIX = "doci:ckpt:"


@contextmanager
def _suppress_tracing():
    """Suppress OTel auto-instrumentation for the duration of the block.

    The checkpointer fires many low-level Valkey commands (HSET/HKEYS/SADD/
    EXPIRE) on every node step; left traced they flood the trace UI and bury the
    agent spans. Suppressing here drops only the *checkpointer's* redis spans —
    the KV cache and taskiq broker (separate clients) keep tracing.
    """
    token = _otel_ctx.attach(_otel_ctx.set_value(_SUPPRESS_INSTRUMENTATION_KEY, True))
    try:
        yield
    finally:
        _otel_ctx.detach(token)


def _untraced(fn: Callable) -> Callable:
    """Run an async checkpointer method with redis tracing suppressed."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _suppress_tracing():
            return await fn(*args, **kwargs)

    return wrapper


def _s(value: Any) -> str:
    """Decode a Valkey reply (bytes) to str."""
    return value.decode() if isinstance(value, (bytes, bytearray)) else value


@dataclass(frozen=True, slots=True)
class CheckpointConfig:
    """Connection + retention config for the Valkey checkpointer."""

    url: str = _DEFAULT_URL
    ttl: int = _DEFAULT_TTL  # seconds; applied to every checkpoint key
    prefix: str = _DEFAULT_PREFIX

    @classmethod
    def from_env(cls) -> "CheckpointConfig":
        """Read ``DOCI_CHECKPOINT_REDIS_URL`` / ``DOCI_CHECKPOINT_TTL``.

        Note: defaults reference the module constants, not ``cls.<field>`` — with
        ``slots=True`` the latter is the slot descriptor, not the default value.
        """
        return cls(
            url=os.getenv("DOCI_CHECKPOINT_REDIS_URL", _DEFAULT_URL),
            ttl=int(os.getenv("DOCI_CHECKPOINT_TTL", str(_DEFAULT_TTL))),
            prefix=os.getenv("DOCI_CHECKPOINT_PREFIX", _DEFAULT_PREFIX),
        )


class ValkeySaver(BaseCheckpointSaver[str]):
    """Durable LangGraph checkpoints in Valkey, TTL-expired."""

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        ttl: int = _DEFAULT_TTL,
        prefix: str = "doci:ckpt:",
    ) -> None:
        super().__init__()
        self._r = client
        self._ttl = ttl
        self._p = prefix

    @property
    def ttl(self) -> int:
        """Seconds each checkpoint key lives before self-expiring."""
        return self._ttl

    # region key helpers
    def _cp(self, thread: str, ns: str, cid: str) -> str:
        return f"{self._p}cp:{thread}:{ns}:{cid}"

    def _idx(self, thread: str, ns: str) -> str:
        return f"{self._p}idx:{thread}:{ns}"

    def _w(self, thread: str, ns: str, cid: str) -> str:
        return f"{self._p}w:{thread}:{ns}:{cid}"

    # endregion

    @_untraced
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        cid = checkpoint["id"]
        parent = config["configurable"].get("checkpoint_id") or ""
        cp_t, cp_b = self.serde.dumps_typed(checkpoint)  # channel_values inline
        md_t, md_b = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))

        cp_key, idx_key = self._cp(thread, ns, cid), self._idx(thread, ns)
        pipe = self._r.pipeline(transaction=False)
        pipe.hset(
            cp_key,
            mapping={
                "cp_t": cp_t,
                "cp": cp_b,
                "md_t": md_t,
                "md": md_b,
                "parent": parent,
            },
        )
        pipe.expire(cp_key, self._ttl)
        pipe.sadd(idx_key, cid)
        pipe.expire(idx_key, self._ttl)
        await pipe.execute()
        return {
            "configurable": {
                "thread_id": thread,
                "checkpoint_ns": ns,
                "checkpoint_id": cid,
            }
        }

    @_untraced
    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        cid = config["configurable"]["checkpoint_id"]
        w_key = self._w(thread, ns, cid)
        existing = {_s(k) for k in await cast(Awaitable[list], self._r.hkeys(w_key))}

        pipe = self._r.pipeline(transaction=False)
        wrote = False
        for idx, (channel, value) in enumerate(writes):
            widx = WRITES_IDX_MAP.get(channel, idx)
            field = f"{task_id}:{widx}"
            if widx >= 0 and field in existing:
                continue  # idempotent: keep the first write for this slot
            vt, vb = self.serde.dumps_typed(value)
            pipe.hset(
                w_key, field, ormsgpack.packb([task_id, channel, vt, vb, task_path])
            )
            wrote = True
        if wrote:
            pipe.expire(w_key, self._ttl)
            await pipe.execute()

    @_untraced
    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        cid = get_checkpoint_id(config)
        if not cid:
            cid = await self._latest(thread, ns)
            if cid is None:
                return None

        data = await cast(Awaitable[dict], self._r.hgetall(self._cp(thread, ns, cid)))
        if not data:
            return None
        data = {_s(k): v for k, v in data.items()}
        checkpoint = self.serde.loads_typed((_s(data["cp_t"]), data["cp"]))
        metadata = self.serde.loads_typed((_s(data["md_t"]), data["md"]))
        parent = _s(data.get("parent") or "")

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread,
                    "checkpoint_ns": ns,
                    "checkpoint_id": cid,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread,
                        "checkpoint_ns": ns,
                        "checkpoint_id": parent,
                    }
                }
                if parent
                else None
            ),
            pending_writes=await self._writes(thread, ns, cid),
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return  # cross-thread listing isn't supported
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        before_id = get_checkpoint_id(before) if before else None
        only_id = get_checkpoint_id(config)
        with _suppress_tracing():
            members = await cast(Awaitable[set], self._r.smembers(self._idx(thread, ns)))
        ids = sorted((_s(i) for i in members), reverse=True)
        for cid in ids:
            if only_id and cid != only_id:
                continue
            if before_id and cid >= before_id:
                continue
            tup = await self.aget_tuple(
                {
                    "configurable": {
                        "thread_id": thread,
                        "checkpoint_ns": ns,
                        "checkpoint_id": cid,
                    }
                }
            )
            if tup is None:
                continue
            if filter and not all(tup.metadata.get(k) == v for k, v in filter.items()):
                continue
            if limit is not None:
                if limit <= 0:
                    break
                limit -= 1
            yield tup

    @_untraced
    async def adelete_thread(self, thread_id: str) -> None:
        pattern = f"{self._p}*:{thread_id}:*"
        keys = [k async for k in self._r.scan_iter(match=pattern)]
        keys.append(self._idx(thread_id, ""))  # also any default-ns index
        if keys:
            await self._r.delete(*keys)

    def get_next_version(self, current: str | None, channel: None) -> str:
        if current is None:
            cur = 0
        elif isinstance(current, int):
            cur = current
        else:
            cur = int(current.split(".")[0])
        return f"{cur + 1:032}.{os.urandom(8).hex()}"

    # region async-only guards
    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError("ValkeySaver is async-only; use aget_tuple")

    def list(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("ValkeySaver is async-only; use alist")

    def put(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("ValkeySaver is async-only; use aput")

    def put_writes(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("ValkeySaver is async-only; use aput_writes")

    # endregion

    # region internals
    async def _latest(self, thread: str, ns: str) -> str | None:
        ids = await cast(Awaitable[set], self._r.smembers(self._idx(thread, ns)))
        return max((_s(i) for i in ids), default=None)

    async def _writes(self, thread: str, ns: str, cid: str) -> list[PendingWrite]:
        raw = await cast(Awaitable[dict], self._r.hgetall(self._w(thread, ns, cid)))
        rows = []
        for field, packed in raw.items():
            task_id, channel, vt, vb, _path = ormsgpack.unpackb(packed)
            rows.append((_s(field), task_id, channel, self.serde.loads_typed((vt, vb))))
        # deterministic order: by task id, then write index
        rows.sort(key=lambda r: (r[1], int(r[0].rsplit(":", 1)[1])))
        return [(task_id, channel, value) for _f, task_id, channel, value in rows]

    # endregion


def build_saver(config: CheckpointConfig | None = None) -> ValkeySaver:
    """Build a ``ValkeySaver`` from config (env by default)."""
    cfg = config or CheckpointConfig.from_env()
    client = aioredis.Redis.from_url(cfg.url)  # bytes mode (no decode_responses)
    return ValkeySaver(client, ttl=cfg.ttl, prefix=cfg.prefix)


async def aclose(saver: ValkeySaver) -> None:
    """Close the saver's Valkey client."""
    await saver._r.aclose()
