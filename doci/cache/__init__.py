"""Cache — ephemeral KV-first / in-memory cache and a caching decorator."""

from doci.cache.cache import Cache, CacheMode
from doci.cache.decorators import cache, configure

__all__ = [
    "Cache",
    "CacheMode",
    "cache",
    "configure",
]