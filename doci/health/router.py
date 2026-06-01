"""FastAPI router exposing the health probes as HTTP endpoints.

- ``GET /livez``  — always 200 while the process is up.
- ``GET /readyz`` — 200 when ``ok``/``degraded``, 503 when ``unavailable``.

Response shapes are documented for OpenAPI via the Pydantic models below.
"""

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from doci.health.service import HealthService, HealthStatus


class CheckResultModel(BaseModel):
    """Result of probing a single dependency."""

    ok: bool = Field(description="Whether the dependency responded successfully.")
    critical: bool = Field(
        description="If true, a failure makes the service unavailable; "
        "if false, a failure only degrades it."
    )
    latency_ms: float = Field(description="Probe round-trip time in milliseconds.")
    error: str | None = Field(default=None, description="Failure detail when not ok.")


class HealthReportModel(BaseModel):
    """Overall health status plus per-dependency detail."""

    status: Literal["ok", "degraded", "unavailable"] = Field(
        description="ok = all up; degraded = a non-critical dependency (kv) is down; "
        "unavailable = a critical dependency (postgres/objstore) is down."
    )
    checks: dict[str, CheckResultModel] = Field(
        default_factory=dict, description="Per-dependency probe results, keyed by name."
    )


_LIVE_EXAMPLE = {"status": "ok", "checks": {}}
_READY_OK = {
    "status": "ok",
    "checks": {
        "postgres": {"ok": True, "critical": True, "latency_ms": 1.2},
        "objstore": {"ok": True, "critical": True, "latency_ms": 3.4},
        "kv": {"ok": True, "critical": False, "latency_ms": 0.5},
    },
}
_READY_DEGRADED = {
    "status": "degraded",
    "checks": {
        "postgres": {"ok": True, "critical": True, "latency_ms": 1.2},
        "objstore": {"ok": True, "critical": True, "latency_ms": 3.4},
        "kv": {"ok": False, "critical": False, "latency_ms": 2000.0, "error": "down"},
    },
}
_READY_UNAVAILABLE = {
    "status": "unavailable",
    "checks": {
        "postgres": {"ok": False, "critical": True, "latency_ms": 2000.0, "error": "timeout"},
        "objstore": {"ok": True, "critical": True, "latency_ms": 3.4},
        "kv": {"ok": True, "critical": False, "latency_ms": 0.5},
    },
}


def build_health_router(health: HealthService) -> APIRouter:
    """Build an APIRouter wired to the given :class:`HealthService`."""
    router = APIRouter(tags=["health"])

    @router.get(
        "/livez",
        summary="Liveness probe",
        description="Always returns 200 while the process can serve requests. "
        "Does not probe dependencies — use it to detect a hung/dead process.",
        response_model=HealthReportModel,
        responses={200: {"content": {"application/json": {"example": _LIVE_EXAMPLE}}}},
    )
    async def livez() -> HealthReportModel:
        return HealthReportModel(**health.livez().to_dict())

    @router.get(
        "/readyz",
        summary="Readiness probe",
        description="Probes dependencies. Returns 200 when **ok** or **degraded** "
        "(kv down), and 503 when **unavailable** (postgres or objstore down).",
        response_model=HealthReportModel,
        responses={
            200: {
                "description": "Ready — ok, or degraded (non-critical dependency down).",
                "content": {
                    "application/json": {
                        "examples": {
                            "ok": {"value": _READY_OK},
                            "degraded": {"value": _READY_DEGRADED},
                        }
                    }
                },
            },
            503: {
                "description": "Not ready — a critical dependency is down.",
                "model": HealthReportModel,
                "content": {"application/json": {"example": _READY_UNAVAILABLE}},
            },
        },
    )
    async def readyz(response: Response) -> HealthReportModel:
        report = await health.readyz()
        # degraded still serves traffic (200); only unavailable pulls from rotation.
        if report.status is HealthStatus.UNAVAILABLE:
            response.status_code = 503
        return HealthReportModel(**report.to_dict())

    return router