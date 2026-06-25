"""Regression: the Postgres pool must BOUND concurrent connections and QUEUE.

The audit deep agent fans out hundreds of simultaneous DB calls. The pool must
cap real server connections at ``max_size`` and make the surplus callers *wait*
for a free connection — never raise / never flood the server (which is what took
the service down with ``POSTGRES_POOL_MAX=200``).

DB-backed (uses the local Postgres from ``docker/compose.postgres.yml``,
creds doci/doci, db doci); skipped automatically when no database is reachable,
so the pure-unit suite still runs clean.
"""

import asyncio
import os

import pytest

from doci.postgres.client import Postgres
from doci.postgres.config import PostgresConfig

# Test pool is deliberately tiny so a burst would exhaust it without queueing.
_MAX = 5
_BURST = 100
_TEST_APP = "doci_pooltest"
_OBS_APP = "doci_poolobs"


def _cfg(*, application_name: str, pool_max: int) -> PostgresConfig:
    """Local-DB config (discrete fields, ssl disabled), overridable via PG* env."""
    return PostgresConfig(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "doci"),
        user=os.getenv("PGUSER", "doci"),
        password=os.getenv("PGPASSWORD", "doci"),
        sslmode=os.getenv("PGSSLMODE", "disable"),
        application_name=application_name,
        pool_min=1,
        pool_max=pool_max,
    )


async def _reachable() -> bool:
    try:
        pg = Postgres(_cfg(application_name="doci_poolprobe", pool_max=1))
        if hasattr(pg, "open"):
            await pg.open()
        try:
            await pg.ping()
        finally:
            await _aclose(pg)
        return True
    except Exception:
        return False


async def _aclose(pg: Postgres) -> None:
    close = getattr(pg, "aclose", None) or pg.close
    res = close()
    if asyncio.iscoroutine(res):
        await res


async def _peak_connections(stop: asyncio.Event, sink: list[int]) -> None:
    """Poll pg_stat_activity for the *test* pool's connection count; record peak."""
    obs = Postgres(_cfg(application_name=_OBS_APP, pool_max=2))
    if hasattr(obs, "open"):
        await obs.open()
    try:
        while not stop.is_set():
            n = await obs.fetch_val(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s",
                [_TEST_APP],
            )
            sink.append(int(n))
            await asyncio.sleep(0.005)
    finally:
        await _aclose(obs)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def db_available() -> bool:
    if not _run(_reachable()):
        pytest.skip("local Postgres not reachable (docker/compose.postgres.yml)")
    return True


def test_concurrent_queries_queue_and_stay_bounded(db_available):
    """~100 concurrent queries through a pool of 5: all succeed, peak conns <= 5."""

    async def scenario() -> tuple[list, list[int]]:
        pg = Postgres(_cfg(application_name=_TEST_APP, pool_max=_MAX))
        if hasattr(pg, "open"):
            await pg.open()
        stop = asyncio.Event()
        peaks: list[int] = []
        observer = asyncio.create_task(_peak_connections(stop, peaks))
        try:
            results = await asyncio.gather(
                *(pg.fetch_val("SELECT 1 FROM pg_sleep(0.05)") for _ in range(_BURST)),
                return_exceptions=True,
            )
        finally:
            stop.set()
            await observer
            await _aclose(pg)
        return results, peaks

    results, peaks = _run(scenario())

    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, f"queries must queue, not raise; got {errors[:3]}"
    assert all(r == 1 for r in results), "all queries must complete"
    assert peaks, "observer recorded no samples"
    assert max(peaks) <= _MAX, f"peak connections {max(peaks)} exceeded max_size {_MAX}"


def test_transactions_stay_bounded(db_available):
    """Concurrent transactions also queue through the bounded pool."""

    async def scenario() -> tuple[list, list[int]]:
        pg = Postgres(_cfg(application_name=_TEST_APP, pool_max=_MAX))
        if hasattr(pg, "open"):
            await pg.open()
        stop = asyncio.Event()
        peaks: list[int] = []
        observer = asyncio.create_task(_peak_connections(stop, peaks))

        async def one() -> int:
            async with pg.transaction() as tx:
                return await tx.fetch_val("SELECT 1 FROM pg_sleep(0.05)")

        try:
            results = await asyncio.gather(
                *(one() for _ in range(_BURST)), return_exceptions=True
            )
        finally:
            stop.set()
            await observer
            await _aclose(pg)
        return results, peaks

    results, peaks = _run(scenario())

    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, f"transactions must queue, not raise; got {errors[:3]}"
    assert max(peaks) <= _MAX, f"peak connections {max(peaks)} exceeded max_size {_MAX}"


def test_prepared_statements_disabled_for_supavisor():
    """psycopg3 connect kwargs must disable server-side prepared statements.

    Supavisor transaction-mode pooling breaks unless prepare_threshold is None.
    Pure-unit (no DB).
    """
    kwargs = _cfg(application_name="x", pool_max=1).connect_kwargs()
    assert kwargs.get("prepare_threshold", "MISSING") is None
