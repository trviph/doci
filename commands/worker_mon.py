"""Developer task-monitor entrypoint (``doci-worker-mon``).

A small, read-mostly JSON service for inspecting task runs: list by state, view a
task's result, and re-run a failed one. Separate from the API and the worker — it
neither serves the product API nor executes tasks (re-kick is by name). It needs
only Valkey, so worker startup (Postgres / object store / LangGraph) never fires.

Import order mirrors the other entrypoints: ``doci.telemetry`` first so the broker
is auto-instrumented at construction.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from taskiq_redis import RedisScheduleSource

import doci.telemetry  # noqa: F401
from doci.taskiq import TaskiqConfig
from doci.taskiq.broker import broker
from doci.taskiq.monitor import TaskMonitor, build_task_monitor_router


def _make_lifespan(manage_broker: bool):
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = TaskiqConfig.from_env()
        monitor = TaskMonitor(
            cfg.broker_url, prefix=cfg.monitor_prefix, ttl=cfg.monitor_ttl_s
        )
        await monitor.aopen()
        await app.state.schedule_source.startup()
        # Standalone: own the broker (CLIENT_STARTUP only — is_worker_process stays
        # False, so no clients are built; inits the result backend + connection +
        # monitor writer client and declares the group). Embedded in all-in-one the
        # API app + receiver already start the broker, so we must NOT start it again.
        if manage_broker:
            await broker.startup()
        app.state.monitor = monitor
        try:
            yield
        finally:
            if manage_broker:
                await broker.shutdown()
            await app.state.schedule_source.shutdown()
            await monitor.aclose()

    return _lifespan


def create_mon_app(*, manage_broker: bool = True) -> FastAPI:
    """Build the worker-monitor ASGI app.

    ``manage_broker`` controls broker lifecycle: ``True`` for the standalone
    command, ``False`` when embedded in all-in-one (where the API app already
    starts/stops the shared broker).
    """
    cfg = TaskiqConfig.from_env()
    schedule_source = RedisScheduleSource(cfg.broker_url)
    app = FastAPI(title="DocI Worker Monitor", lifespan=_make_lifespan(manage_broker))
    app.state.schedule_source = schedule_source
    app.include_router(build_task_monitor_router(broker, schedule_source))
    return app


app = create_mon_app()


def main() -> None:
    uvicorn.run(
        app,
        host=os.getenv("MON_HOST", "localhost"),
        port=int(os.getenv("MON_PORT", "8001")),
    )


if __name__ == "__main__":
    main()
