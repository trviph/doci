"""Configuration for the key-value (Valkey/Redis) client.

A connection URL takes precedence; otherwise discrete ``REDIS_*`` fields are
assembled. Mirrors the ``os.getenv``-with-default style used elsewhere.
"""

import os
from dataclasses import dataclass
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class KVConfig:
    """Connection + namespacing configuration for a :class:`KV` client."""

    url: str | None = None
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    ssl: bool = False
    key_prefix: str = ""
    default_ttl: int | None = None
    max_connections: int = 10

    @classmethod
    def from_env(cls) -> "KVConfig":
        """Build a config from ``REDIS_URL`` or discrete ``REDIS_*`` env vars."""
        ttl = os.getenv("REDIS_DEFAULT_TTL")
        return cls(
            url=os.getenv("REDIS_URL"),
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD"),
            ssl=_env_bool("REDIS_SSL", False),
            key_prefix=os.getenv("REDIS_KEY_PREFIX", ""),
            default_ttl=int(ttl) if ttl else None,
            max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "10")),
        )

    def client_kwargs(self) -> dict[str, Any]:
        """Keyword args for the redis client.

        URL set → ``{"url": ...}`` (build with ``Redis.from_url``); otherwise
        discrete connection fields. Both decode responses to ``str`` and bound
        the connection pool.
        """
        common: dict[str, Any] = {
            "decode_responses": True,
            "max_connections": self.max_connections,
        }
        if self.url:
            return {"url": self.url, **common}
        return {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "password": self.password,
            "ssl": self.ssl,
            **common,
        }
