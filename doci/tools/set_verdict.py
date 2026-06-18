"""Tool: set the dossier-level audit verdict.

Service-backed (factory). Bound to the audit run's ``execution_id`` + the
dossier/document under audit; upserts the §7 conclusion (pass / needs_review /
fail) with a rationale. Call once, after recording findings.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.audit import AuditService

_VERDICT = {"pass", "needs_review", "fail"}


def build_set_verdict(
    audit: AuditService,
    execution_id: UUID,
    dossier_key: str | None,
    document_id: UUID | None,
) -> StructuredTool:
    async def set_verdict(verdict: str, rationale: str) -> dict:
        """Set the dossier verdict (pass | needs_review | fail) with a short
        rationale. PASS only if no fail/blocking finding; FAIL on a missing
        required document, material amount/tax error, serious LOA/SoD breach,
        blacklisted vendor, or duplicate payment; otherwise NEEDS_REVIEW."""
        if verdict not in _VERDICT:
            return {
                "ok": False,
                "error": f"verdict must be one of {sorted(_VERDICT)}, got {verdict!r}.",
            }
        v = await audit.set_verdict(
            execution_id=execution_id,
            dossier_key=dossier_key,
            document_id=document_id,
            verdict=verdict,
            rationale=rationale,
        )
        return {"ok": True, "verdict": v.verdict}

    return tool(set_verdict)
