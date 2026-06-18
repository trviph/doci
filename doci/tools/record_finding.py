"""Tool: record one audit finding.

Service-backed (factory). Bound to the audit run's ``execution_id``; persists a
finding (status + severity + message + evidence) to ``audit_finding``. Evidence
should quote the ``facts.source`` text the finding rests on.
"""

from typing import Any
from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.audit import AuditService

_STATUS = {"pass", "fail", "needs_review"}


def build_record_finding(audit: AuditService, execution_id: UUID) -> StructuredTool:
    async def record_finding(
        status: str,
        severity: str,
        message: str,
        rule_key: str | None = None,
        evidence: list[Any] | None = None,
    ) -> dict:
        """Record one audit finding. status ∈ {pass, fail, needs_review}; severity
        e.g. info|low|medium|high|critical|block; message is the human explanation;
        evidence is a list of the source quotes / page refs it rests on. Use
        needs_review (with the reason in message) when a check cannot be verified."""
        if status not in _STATUS:
            return {
                "ok": False,
                "error": f"status must be one of {sorted(_STATUS)}, got {status!r}.",
            }
        if not (message and message.strip()):
            return {"ok": False, "error": "message is required (explain the finding)."}
        f = await audit.record_finding(
            execution_id=execution_id,
            rule_key=rule_key,
            severity=severity,
            status=status,
            message=message,
            evidence=evidence,
        )
        return {"ok": True, "finding_id": str(f.id)}

    return tool(record_finding)
