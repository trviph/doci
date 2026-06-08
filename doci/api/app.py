"""FastAPI application factory.

`create_app()` assembles the ASGI app: it builds the shared clients (Postgres,
ObjStore, KV) in the lifespan, mounts the health router, and instruments the app
for OpenTelemetry. Deployment entrypoints live in the top-level ``commands``
package and import this factory, so multiple deployment types can share one app.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Importing doci.telemetry registers the OTel providers + library instrumentation
# (botocore/psycopg2/redis) and exposes shutdown().
from doci import telemetry
from doci.bootstrap import build_clients, close_clients
from doci.globals import SERVICE_VERSION
from doci.health import HealthService, build_health_router
from doci.helpers import HttpRequestContextMiddleware, InternalAccessError
from doci.media import build_media_router
from doci.taskiq import broker as _taskiq_broker
from doci.workflows.router import build_workflows_router


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Build dependencies once and share them via app.state.
    clients = build_clients()
    app.state.postgres = clients.postgres
    app.state.objstore = clients.objstore
    app.state.kv = clients.kv
    app.state.health = HealthService(
        postgres=clients.postgres, objstore=clients.objstore, kv=clients.kv
    )
    app.state.media = clients.media
    app.state.workflow_runs = clients.workflow_runs
    await _taskiq_broker.startup()
    # Start asyncio runtime metrics (task count + event-loop lag) now that we're
    # inside the running loop; system/process metrics were registered at import.
    telemetry.runtime.start_asyncio_metrics()
    try:
        yield
    finally:
        await telemetry.runtime.stop_asyncio_metrics()
        await _taskiq_broker.shutdown()
        await close_clients(clients)
        telemetry.shutdown()


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(title="DocI", version=SERVICE_VERSION, lifespan=_lifespan)
    # Flag HTTP scopes so `@internal` service methods refuse to run during a
    # request; surface any leak as 403 rather than a 500.
    app.add_middleware(HttpRequestContextMiddleware)

    @app.exception_handler(InternalAccessError)
    async def _forbid_internal(
        _request: Request, _exc: InternalAccessError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN, content={"detail": "forbidden"}
        )

    app.include_router(build_health_router())
    app.include_router(build_media_router())
    app.include_router(build_workflows_router())
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.TRACER_PROVIDER,
        meter_provider=telemetry.METER_PROVIDER,
    )
    return app
