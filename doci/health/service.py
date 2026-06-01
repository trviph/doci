"""Health probes for the service and its dependencies.

``livez`` is a pure liveness signal (always OK if the process is running).
``readyz`` probes dependencies and classifies readiness by criticality:

- Postgres and ObjStore are **critical** — either down ⇒ ``unavailable``.
- KV (Valkey/Redis) is **non-critical** — down ⇒ ``degraded`` (still serving).
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class Pingable(Protocol):
    """Anything with an async ``ping()`` that raises when unreachable."""

    async def ping(self) -> None: ...


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of probing one dependency."""

    name: str
    ok: bool
    critical: bool
    latency_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "critical": self.critical,
            "latency_ms": round(self.latency_ms, 2),
        }
        if self.error:
            out["error"] = self.error
        return out


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Overall status plus per-dependency detail."""

    status: HealthStatus
    checks: tuple[CheckResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": {c.name: c.to_dict() for c in self.checks},
        }


class HealthService:
    """Composes dependency probes into liveness / readiness reports."""

    def __init__(
        self,
        *,
        postgres: Pingable,
        objstore: Pingable,
        kv: Pingable,
        timeout_seconds: float = 2.0,
    ) -> None:
        # Per-dependency probe timeout, in seconds (passed to asyncio.wait_for).
        self._timeout_seconds = timeout_seconds
        # (name, client, critical) — KV is the only non-critical dependency.
        self._deps: tuple[tuple[str, Pingable, bool], ...] = (
            ("postgres", postgres, True),
            ("objstore", objstore, True),
            ("kv", kv, False),
        )

    def livez(self) -> HealthReport:
        """Liveness: OK as long as the process can answer. No dependency probing."""
        return HealthReport(status=HealthStatus.OK)

    async def readyz(self) -> HealthReport:
        """Readiness: probe all dependencies concurrently and classify by criticality."""
        results = await asyncio.gather(
            *(
                self._probe(name, client, critical)
                for name, client, critical in self._deps
            )
        )
        critical_down = any(not r.ok for r in results if r.critical)
        noncritical_down = any(not r.ok for r in results if not r.critical)
        if critical_down:
            status = HealthStatus.UNAVAILABLE
        elif noncritical_down:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.OK
        return HealthReport(status=status, checks=tuple(results))

    async def _probe(self, name: str, client: Pingable, critical: bool) -> CheckResult:
        start = time.perf_counter()
        try:
            await asyncio.wait_for(client.ping(), self._timeout_seconds)
        except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
            elapsed = (time.perf_counter() - start) * 1000.0
            return CheckResult(
                name, False, critical, elapsed, error=str(exc) or type(exc).__name__
            )
        elapsed = (time.perf_counter() - start) * 1000.0
        return CheckResult(name, True, critical, elapsed)
