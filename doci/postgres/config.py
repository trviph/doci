"""Configuration for the Postgres client.

Read from environment variables following the ``os.getenv``-with-default style
used elsewhere in the package. A full connection string (DSN) takes precedence;
otherwise discrete ``PG*`` fields are assembled.
"""

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    """Connection + pool configuration for a :class:`Postgres` client."""

    dsn: str | None = None
    host: str | None = None
    port: int = 5432
    dbname: str = "postgres"
    user: str | None = None
    password: str | None = None
    sslmode: str = "require"
    connect_timeout: int = 10
    application_name: str = "doci"
    pool_min: int = 1
    pool_max: int = 10

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        """Build a config from ``DATABASE_URL``/``POSTGRES_DSN`` or ``PG*`` env vars."""
        return cls(
            dsn=os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN"),
            host=os.getenv("PGHOST"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "postgres"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            sslmode=os.getenv("PGSSLMODE", "require"),
            connect_timeout=int(os.getenv("PGCONNECT_TIMEOUT", "10")),
            application_name=os.getenv("PGAPPNAME", "doci"),
            pool_min=int(os.getenv("POSTGRES_POOL_MIN", "1")),
            pool_max=int(os.getenv("POSTGRES_POOL_MAX", "10")),
        )

    def connect_kwargs(self) -> dict[str, Any]:
        """Keyword args passed through the pool to ``psycopg2.connect``.

        When a DSN is set it is used verbatim (so a Supabase pooler URL — incl. its
        ``postgres.<project-ref>`` tenant username and its own ``sslmode`` — is
        respected); only safe extras are added. Otherwise discrete fields, with
        ``sslmode`` applied, are used.
        """
        common: dict[str, Any] = {
            "connect_timeout": self.connect_timeout,
            "application_name": self.application_name,
        }
        if self.dsn:
            return {"dsn": self.dsn, **common}
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "sslmode": self.sslmode,
            **common,
        }