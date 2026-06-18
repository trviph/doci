"""Value objects for audit results (framework-agnostic).

An :class:`AuditFinding` is one observation the audit agent records for a rule/
check (a status + severity + message + the evidence it rests on); an
:class:`AuditVerdict` is the dossier-level conclusion for the run (§7). Both hang
off the audit ``workflow_execution`` row via ``execution_id``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """One audit observation. ``evidence`` is a list of ``{part_id?, page?, quote}``
    drawn from the mined ``facts.source`` quotes the finding rests on."""

    id: UUID
    execution_id: UUID
    rule_key: str | None
    severity: str  # info | low | medium | high | critical | block
    status: str  # pass | fail | needs_review
    message: str
    evidence: list[Any]
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AuditFinding":
        return cls(
            id=row["id"],
            execution_id=row["execution_id"],
            rule_key=row["rule_key"],
            severity=row["severity"],
            status=row["status"],
            message=row["message"],
            evidence=row["evidence"] or [],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class AuditVerdict:
    """The dossier-level conclusion for one audit run."""

    execution_id: UUID
    dossier_key: str | None
    document_id: UUID | None
    verdict: str  # pass | needs_review | fail
    rationale: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AuditVerdict":
        return cls(
            execution_id=row["execution_id"],
            dossier_key=row["dossier_key"],
            document_id=row["document_id"],
            verdict=row["verdict"],
            rationale=row["rationale"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
