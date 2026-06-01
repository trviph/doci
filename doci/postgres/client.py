"""Postgres client over a psycopg2 connection pool.

Exposes an ``async`` API that offloads blocking psycopg2 calls with
:func:`asyncio.to_thread`, so it can be awaited from FastAPI handlers without
blocking the event loop. Works against a direct Postgres connection and the
Supabase Supavisor pooler (psycopg2 uses no server-side prepared statements, so
transaction-mode pooling needs no special handling).
"""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry.trace import SpanKind, get_current_span
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from doci.postgres.config import PostgresConfig
from doci.telemetry import Counter, current_report, traced, with_metrics, with_span

#: Rows returned by fetch_all, for visibility into result-set sizes.
PG_ROWS = Counter("doci.postgres.rows", description="Rows returned by fetch_all")

_Params = Sequence[Any] | Mapping[str, Any] | None


def _annotate() -> None:
    get_current_span().set_attribute("db.system", "postgresql")


def _exec(conn: Any, query: str, params: _Params, fetch: str) -> Any:
    """Run ``query`` on ``conn`` and return the requested result shape.

    ``fetch`` is one of ``"all"`` / ``"one"`` / ``"val"`` / ``"none"``. Does not
    commit — the caller owns transaction boundaries.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        if fetch == "all":
            return cur.fetchall()
        if fetch == "one":
            return cur.fetchone()
        if fetch == "val":
            row = cur.fetchone()
            return next(iter(row.values())) if row else None
        return cur.rowcount


@traced
class Transaction:
    """A unit of work pinned to one pooled connection.

    Obtained from :meth:`Postgres.transaction`; statements run on the same
    connection and are committed (or rolled back) once when the context exits.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_all(
        self, query: str, params: _Params = None
    ) -> list[dict[str, Any]]:
        _annotate()
        return await asyncio.to_thread(_exec, self._conn, query, params, "all")

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_one(
        self, query: str, params: _Params = None
    ) -> dict[str, Any] | None:
        _annotate()
        return await asyncio.to_thread(_exec, self._conn, query, params, "one")

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_val(self, query: str, params: _Params = None) -> Any:
        _annotate()
        return await asyncio.to_thread(_exec, self._conn, query, params, "val")

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def execute(self, query: str, params: _Params = None) -> int:
        _annotate()
        return await asyncio.to_thread(_exec, self._conn, query, params, "none")


@traced
class Postgres:
    """Async Postgres client backed by a thread-safe connection pool.

    Construct with a :class:`PostgresConfig` (or :meth:`from_env`) and inject it
    where database access is needed.
    """

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._pool = ThreadedConnectionPool(
            config.pool_min, config.pool_max, **config.connect_kwargs()
        )

    @classmethod
    def from_env(cls) -> "Postgres":
        return cls(PostgresConfig.from_env())

    # -- lifecycle -------------------------------------------------------- #
    def close(self) -> None:
        """Close all pooled connections. Call on application shutdown."""
        self._pool.closeall()

    def __enter__(self) -> "Postgres":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals -------------------------------------------------------- #
    def _run(self, query: str, params: _Params, fetch: str) -> Any:
        conn = self._pool.getconn()
        try:
            result = _exec(conn, query, params, fetch)
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    # -- query helpers (auto-commit, one pooled connection each) ---------- #
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_all(
        self, query: str, params: _Params = None
    ) -> list[dict[str, Any]]:
        _annotate()
        rows = await asyncio.to_thread(self._run, query, params, "all")
        current_report().record(PG_ROWS, len(rows))
        return rows

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_one(
        self, query: str, params: _Params = None
    ) -> dict[str, Any] | None:
        _annotate()
        return await asyncio.to_thread(self._run, query, params, "one")

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_val(self, query: str, params: _Params = None) -> Any:
        _annotate()
        return await asyncio.to_thread(self._run, query, params, "val")

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def execute(self, query: str, params: _Params = None) -> int:
        _annotate()
        return await asyncio.to_thread(self._run, query, params, "none")

    # -- multi-statement transaction -------------------------------------- #
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """Pin one pooled connection across statements; commit on exit, rollback on error."""
        conn = await asyncio.to_thread(self._pool.getconn)
        try:
            yield Transaction(conn)
            await asyncio.to_thread(conn.commit)
        except BaseException:
            await asyncio.to_thread(conn.rollback)
            raise
        finally:
            self._pool.putconn(conn)
