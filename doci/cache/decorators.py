"""Caching decorator for async functions.

The simple path: register a KV once with :func:`configure`, then decorate async
functions with :func:`cache`. Each decorated function gets its own auto-built
:class:`Cache` (namespaced by the function's qualified name). For anything beyond
this, construct a :class:`Cache` directly and use it (it's injectable).
"""

import functools
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from doci.cache.cache import Cache, CacheMode
from doci.kvstore import KV

_P = ParamSpec("_P")
_R = TypeVar("_R")

_DEFAULT_KV: KV | None = None


def configure(kv: KV | None = None) -> None:
    """Register the KV used by KV-mode :func:`cache` decorators.

    Call once at application startup. In-memory-only decorators need no config.
    """
    global _DEFAULT_KV
    _DEFAULT_KV = kv


def _build_cache(mode: CacheMode, namespace: str, maxsize: int) -> Cache:
    if mode is CacheMode.KV_THEN_MEM and _DEFAULT_KV is None:
        raise RuntimeError(
            "cache(mode=KV_THEN_MEM) requires a KV — call doci.cache.configure(kv=...) "
            "at startup, or use mode=CacheMode.MEM_ONLY."
        )
    return Cache(mode=mode, kv=_DEFAULT_KV, namespace=namespace, maxsize=maxsize)


def _resolve_key(
    func: Callable[..., Any],
    key: str | Callable[..., str] | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    if callable(key):
        return key(*args, **kwargs)
    if isinstance(key, str):
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        return key.format(**bound.arguments)
    return f"{func.__qualname__}:{json.dumps([args, kwargs], default=str, sort_keys=True)}"


def cache(
    key: str | Callable[..., str] | None = None,
    *,
    mode: CacheMode = CacheMode.MEM_ONLY,
    ttl: int,
    maxsize: int = 1024,
) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]:
    """Memoize an ``async`` function's result in an auto-managed :class:`Cache`.

    ``key`` is a ``str`` template formatted with the call's bound arguments by name
    (e.g. ``"presign:{k}"``), a callable ``(*args, **kwargs) -> str``, or ``None``
    (a default key derived from the function name + arguments). ``None`` results are
    treated as misses and never cached.
    """

    def decorate(func: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
        store: Cache | None = None

        @functools.wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            nonlocal store
            if store is None:  # lazy so configure() has run by call time
                store = _build_cache(mode, func.__qualname__, maxsize)
            cache_key = _resolve_key(func, key, args, kwargs)
            hit = await store.get(cache_key)
            if hit is not None:
                return hit
            result = await func(*args, **kwargs)
            if result is not None:
                await store.set(cache_key, result, ttl=ttl)
            return result

        return wrapper

    return decorate