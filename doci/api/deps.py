"""FastAPI dependencies resolving the shared clients from ``app.state``.

The clients are constructed once in the app lifespan (see :mod:`doci.api.app`)
and stored on ``app.state``; these helpers expose them to route handlers via
``Depends``.
"""

from fastapi import Request

from doci.health import HealthService
from doci.kvstore import KV
from doci.objstore import ObjStore
from doci.postgres import Postgres


def get_postgres(request: Request) -> Postgres:
    return request.app.state.postgres


def get_objstore(request: Request) -> ObjStore:
    return request.app.state.objstore


def get_kv(request: Request) -> KV:
    return request.app.state.kv


def get_health(request: Request) -> HealthService:
    return request.app.state.health
