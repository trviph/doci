"""Postgres client over a psycopg (psycopg3) async connection pool.

Exposes an ``async`` API backed by :class:`psycopg_pool.AsyncConnectionPool`.
The pool's ``max_size`` hard-caps live server connections and ``connection()``
*blocks up to ``timeout``* for a free connection — so a burst of concurrent
callers (e.g. the audit agent's fan-out) QUEUES through a small reused pool
instead of opening connections without bound. Works against a direct Postgres
connection and the Supabase Supavisor pooler (``prepare_threshold=None`` disables
server-side prepared statements, which transaction-mode pooling cannot carry).
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry.trace import SpanKind, get_current_span
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from doci.postgres.config import PostgresConfig
from doci.telemetry import Counter, current_report, traced, with_metrics, with_span

#: Rows returned by fetch_all, for visibility into result-set sizes.
PG_ROWS = Counter("doci.postgres.rows", description="Rows returned by fetch_all")

_Params = Sequence[Any] | Mapping[str, Any] | None


def _annotate() -> None:
    get_current_span().set_attribute("db.system", "postgresql")


def _val(row: dict[str, Any] | None) -> Any:
    """First column of a single row (or ``None``)."""
    return next(iter(row.values())) if row else None


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
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_one(
        self, query: str, params: _Params = None
    ) -> dict[str, Any] | None:
        _annotate()
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_val(self, query: str, params: _Params = None) -> Any:
        _annotate()
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            return _val(await cur.fetchone())

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def execute(self, query: str, params: _Params = None) -> int:
        _annotate()
        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            return cur.rowcount


@traced
class Postgres:
    """Async Postgres client backed by a bounded, blocking connection pool.

    Construct with a :class:`PostgresConfig` (or :meth:`from_env`), then
    :meth:`open` it inside the running event loop; inject it where database
    access is needed and :meth:`aclose` on shutdown.
    """

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._pool = AsyncConnectionPool(
            conninfo=config.conninfo(),
            kwargs={**config.connect_kwargs(), "row_factory": dict_row},
            min_size=config.pool_min,
            max_size=config.pool_max,
            timeout=config.pool_timeout,
            open=False,
        )

    @classmethod
    def from_env(cls) -> "Postgres":
        return cls(PostgresConfig.from_env())

    # region lifecycle
    async def open(self) -> None:
        """Open the pool (must run inside the event loop). Idempotent."""
        await self._pool.open()

    async def ping(self) -> None:
        """Liveness probe; raises if the database is unreachable. Used by health checks."""
        await self.fetch_val("select 1")

    async def aclose(self) -> None:
        """Close all pooled connections. Call on application shutdown."""
        await self._pool.close()

    # endregion

    # region query helpers (auto-commit, one pooled connection each)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_all(
        self, query: str, params: _Params = None
    ) -> list[dict[str, Any]]:
        _annotate()
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
        current_report().record(PG_ROWS, len(rows))
        return rows

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_one(
        self, query: str, params: _Params = None
    ) -> dict[str, Any] | None:
        _annotate()
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def fetch_val(self, query: str, params: _Params = None) -> Any:
        _annotate()
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            return _val(await cur.fetchone())

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def execute(self, query: str, params: _Params = None) -> int:
        _annotate()
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            return cur.rowcount

    # endregion

    # region multi-statement transaction
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """Pin one pooled connection across statements; commit on exit, rollback on error."""
        async with self._pool.connection() as conn:
            yield Transaction(conn)

    # endregion
