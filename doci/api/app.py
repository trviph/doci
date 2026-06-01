"""FastAPI application factory.

`create_app()` assembles the ASGI app: it builds the shared clients (Postgres,
ObjStore, KV) in the lifespan, mounts the health router, and instruments the app
for OpenTelemetry. Deployment entrypoints live in the top-level ``commands``
package and import this factory, so multiple deployment types can share one app.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Importing doci.telemetry registers the OTel providers + library instrumentation
# (botocore/psycopg2/redis) and exposes shutdown().
from doci import telemetry
from doci.globals import SERVICE_VERSION
from doci.health import HealthService, build_health_router
from doci.kvstore import KV
from doci.objstore import ObjStore
from doci.postgres import Postgres


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Build dependencies once and share them via app.state.
    pg = Postgres.from_env()
    obj = ObjStore.from_env()
    kv = KV.from_env()
    app.state.postgres = pg
    app.state.objstore = obj
    app.state.kv = kv
    app.state.health = HealthService(postgres=pg, objstore=obj, kv=kv)
    try:
        yield
    finally:
        await kv.aclose()
        obj.close()
        pg.close()
        telemetry.shutdown()


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(title="DocI", version=SERVICE_VERSION, lifespan=_lifespan)
    app.include_router(build_health_router())
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.TRACER_PROVIDER,
        meter_provider=telemetry.METER_PROVIDER,
    )
    return app
