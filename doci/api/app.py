"""FastAPI application factory.

`create_app()` assembles the ASGI app: it builds the shared clients (Postgres,
ObjStore, KV) in the lifespan, mounts the health router, and instruments the app
for OpenTelemetry. Deployment entrypoints live in the top-level ``commands``
package and import this factory, so multiple deployment types can share one app.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Importing doci.telemetry registers the OTel providers + library instrumentation
# (botocore/psycopg2/redis) and exposes shutdown().
from doci import telemetry
from doci.cache import Cache, CacheMode
from doci.globals import SERVICE_VERSION
from doci.health import HealthService, build_health_router
from doci.helpers import HttpRequestContextMiddleware, InternalAccessError
from doci.kvstore import KV, KVConfig
from doci.media import MediaConfig, MediaService, build_media_router
from doci.objstore import ObjStore
from doci.postgres import Postgres
from doci.taskiq import broker as _taskiq_broker


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Build dependencies once and share them via app.state.
    pg = Postgres.from_env()
    obj = ObjStore.from_env()
    # All doci KV keys are namespaced under `doci:` (db comes from REDIS_DB/REDIS_URL,
    # default 0); db 1 is used by the TaskIQ broker (TASKIQ_BROKER_URL).
    kvcfg = KVConfig.from_env()
    if not kvcfg.key_prefix:
        kvcfg = replace(kvcfg, key_prefix="doci:")
    kv = KV(kvcfg)

    media_config = MediaConfig.from_env()
    media_cache = Cache(
        mode=CacheMode.KV_THEN_MEM,
        kv=kv,
        namespace="media:view",
        default_ttl=media_config.view_cache_ttl,
    )

    app.state.postgres = pg
    app.state.objstore = obj
    app.state.kv = kv
    app.state.health = HealthService(postgres=pg, objstore=obj, kv=kv)
    app.state.media = MediaService(
        postgres=pg, objstore=obj, cache=media_cache, config=media_config
    )
    await _taskiq_broker.startup()
    # Start asyncio runtime metrics (task count + event-loop lag) now that we're
    # inside the running loop; system/process metrics were registered at import.
    telemetry.runtime.start_asyncio_metrics()
    try:
        yield
    finally:
        await telemetry.runtime.stop_asyncio_metrics()
        await _taskiq_broker.shutdown()
        await kv.aclose()
        obj.close()
        pg.close()
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
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.TRACER_PROVIDER,
        meter_provider=telemetry.METER_PROVIDER,
    )
    return app
