"""Key-value client over Valkey/Redis.

Built on the natively-async ``redis.asyncio`` client (with a built-in connection
pool), so methods are genuinely ``async`` — no thread offloading. Designed to be
constructed once and injected as a dependency.
"""

import json
from collections.abc import Sequence
from typing import Any

import redis.asyncio as aioredis
from opentelemetry.trace import SpanKind, get_current_span
from redis.asyncio.client import Redis

from doci.kvstore.config import KVConfig
from doci.telemetry import traced, with_metrics, with_span


def _annotate() -> None:
    get_current_span().set_attribute("db.system", "redis")


def _build_client(config: KVConfig) -> Redis:
    kwargs = config.client_kwargs()
    if "url" in kwargs:
        return aioredis.Redis.from_url(kwargs.pop("url"), **kwargs)
    return aioredis.Redis(**kwargs)


@traced
class KVScript:
    """A registered Lua script, callable with EVALSHA→EVAL fallback.

    Wraps redis-py's ``Script`` (which runs ``EVALSHA``, and on ``NOSCRIPT``
    falls back to ``EVAL`` and caches the sha), adding key-prefixing + telemetry.
    """

    def __init__(self, kv: "KV", lua: str) -> None:
        self._kv = kv
        self._script = kv._redis.register_script(lua)

    @property
    def sha(self) -> str:
        return self._script.sha

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def __call__(
        self, *, keys: Sequence[str] = (), args: Sequence[Any] = ()
    ) -> Any:
        _annotate()
        return await self._script(
            keys=self._kv._keys(keys), args=list(args), client=self._kv._redis
        )


@traced
class KV:
    """Async key-value client for Valkey/Redis.

    Construct with a :class:`KVConfig` (or :meth:`from_env`) and inject it where
    a cache / key-value store is needed. An optional ``key_prefix`` is prepended
    transparently to every key.
    """

    def __init__(self, config: KVConfig) -> None:
        self._config = config
        self._redis: Redis = _build_client(config)
        self._prefix = config.key_prefix
        self._default_ttl = config.default_ttl

    @classmethod
    def from_env(cls) -> "KV":
        return cls(KVConfig.from_env())

    # region lifecycle
    async def aclose(self) -> None:
        """Close the client and its connection pool. Call on application shutdown."""
        await self._redis.aclose()

    async def __aenter__(self) -> "KV":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # endregion

    # region internals
    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _keys(self, keys: Sequence[str]) -> list[str]:
        return [self._key(k) for k in keys]

    def _ttl(self, ttl: int | None) -> int | None:
        return ttl if ttl is not None else self._default_ttl

    # endregion

    # region string ops
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get(self, key: str) -> str | None:
        _annotate()
        return await self._redis.get(self._key(key))

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        _annotate()
        await self._redis.set(self._key(key), value, ex=self._ttl(ttl))

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete(self, *keys: str) -> int:
        _annotate()
        return await self._redis.delete(*self._keys(keys))

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def exists(self, *keys: str) -> int:
        _annotate()
        return await self._redis.exists(*self._keys(keys))

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def expire(self, key: str, ttl: int) -> bool:
        _annotate()
        return await self._redis.expire(self._key(key), ttl)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def ttl(self, key: str) -> int:
        _annotate()
        return await self._redis.ttl(self._key(key))

    # endregion

    # region counters
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def incr(self, key: str, amount: int = 1) -> int:
        _annotate()
        return await self._redis.incrby(self._key(key), amount)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def decr(self, key: str, amount: int = 1) -> int:
        _annotate()
        return await self._redis.decrby(self._key(key), amount)

    # endregion

    # region JSON helpers
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_json(self, key: str) -> Any | None:
        _annotate()
        raw = await self._redis.get(self._key(key))
        return json.loads(raw) if raw is not None else None

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def set_json(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        _annotate()
        await self._redis.set(self._key(key), json.dumps(value), ex=self._ttl(ttl))

    # endregion

    # region scripting
    def script(self, lua: str) -> KVScript:
        """Register a Lua script; the returned callable runs it (EVALSHA→EVAL)."""
        return KVScript(self, lua)

    # endregion
