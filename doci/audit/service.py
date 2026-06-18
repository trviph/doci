"""Audit-result service: persist + read findings and the dossier verdict.

Backs ``audit_finding`` + ``audit_verdict`` (raw SQL over the async
:class:`Postgres` client). The write methods are what the ``record_finding`` /
``set_verdict`` agent tools call; the read methods back a later REST/report
surface.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from opentelemetry.trace import SpanKind
from psycopg2.extras import Json, register_uuid

from doci.audit.models import AuditFinding, AuditVerdict
from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span

register_uuid()

_FINDING_COLS = (
    "id, execution_id, rule_key, severity, status, message, evidence, created_at"
)
_VERDICT_COLS = (
    "execution_id, dossier_key, document_id, verdict, rationale, "
    "created_at, updated_at"
)


@traced
class AuditService:
    """Read/write over ``audit_finding`` + ``audit_verdict``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def record_finding(
        self,
        *,
        execution_id: UUID,
        severity: str,
        status: str,
        message: str,
        rule_key: str | None = None,
        evidence: Sequence[Any] | None = None,
    ) -> AuditFinding:
        """Append one finding for the audit run."""
        row = await self._pg.fetch_one(
            "INSERT INTO audit_finding "
            "(execution_id, rule_key, severity, status, message, evidence) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            f"RETURNING {_FINDING_COLS}",
            [
                execution_id,
                rule_key,
                severity,
                status,
                message,
                Json(list(evidence or [])),
            ],
        )
        return AuditFinding.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def set_verdict(
        self,
        *,
        execution_id: UUID,
        verdict: str,
        dossier_key: str | None = None,
        document_id: UUID | None = None,
        rationale: str | None = None,
    ) -> AuditVerdict:
        """Upsert the run's dossier-level verdict (one per execution)."""
        row = await self._pg.fetch_one(
            "INSERT INTO audit_verdict "
            "(execution_id, dossier_key, document_id, verdict, rationale) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (execution_id) DO UPDATE SET "
            "verdict = EXCLUDED.verdict, rationale = EXCLUDED.rationale, "
            "dossier_key = EXCLUDED.dossier_key, document_id = EXCLUDED.document_id, "
            "updated_at = now() "
            f"RETURNING {_VERDICT_COLS}",
            [execution_id, dossier_key, document_id, verdict, rationale],
        )
        return AuditVerdict.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_findings(self, execution_id: UUID) -> list[AuditFinding]:
        """All findings for a run (creation order)."""
        rows = await self._pg.fetch_all(
            f"SELECT {_FINDING_COLS} FROM audit_finding WHERE execution_id = %s "
            "ORDER BY created_at, id",
            [execution_id],
        )
        return [AuditFinding.from_row(r) for r in rows]

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_verdict(self, execution_id: UUID) -> AuditVerdict | None:
        """The run's verdict, or ``None`` if not set yet."""
        row = await self._pg.fetch_one(
            f"SELECT {_VERDICT_COLS} FROM audit_verdict WHERE execution_id = %s",
            [execution_id],
        )
        return AuditVerdict.from_row(row) if row else None
