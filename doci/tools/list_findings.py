"""Tool: read the findings recorded for this audit run.

Service-backed (factory). Bound to the audit run's ``execution_id``; the verdict
agent reads the recorded findings (status / severity / message / evidence) to
decide the dossier verdict — it sees only this compact list, not the whole
investigation.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.audit import AuditService


def build_list_findings(audit: AuditService, execution_id: UUID) -> StructuredTool:
    async def list_findings() -> dict:
        """List all findings recorded for this audit run (rule_key, status,
        severity, message, evidence). Base the verdict on these."""
        findings = await audit.list_findings(execution_id)
        return {
            "ok": True,
            "findings": [
                {
                    "rule_key": f.rule_key,
                    "status": f.status,
                    "severity": f.severity,
                    "message": f.message,
                    "evidence": f.evidence,
                }
                for f in findings
            ],
        }

    return tool(list_findings)