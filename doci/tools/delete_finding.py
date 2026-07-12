"""Tool: delete one finding from this audit run.

Service-backed (factory). Bound to the audit run's ``execution_id``; the
reflection (consolidation) pass uses it to remove a duplicate or superseded
finding it identified via ``list_findings`` (by ``id``). Scoped to the run, so it
can only delete this run's own findings.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.audit import AuditService


def build_delete_finding(audit: AuditService, execution_id: UUID) -> StructuredTool:
    async def delete_finding(finding_id: str) -> dict:
        """Delete one finding from this audit run by its ``id`` (from list_findings).
        Use to remove an exact duplicate, or the wrong side of two contradictory
        findings after verifying against the evidence."""
        try:
            fid = UUID(finding_id)
        except ValueError, TypeError:
            return {
                "ok": False,
                "error": f"finding_id must be a UUID, got {finding_id!r}.",
            }
        deleted = await audit.delete_finding(execution_id=execution_id, finding_id=fid)
        return {"ok": True, "deleted": bool(deleted)}

    return tool(delete_finding)
