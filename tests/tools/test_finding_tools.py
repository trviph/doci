"""Finding read/delete tools used by the reflection (consolidation) pass."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from doci.audit.models import AuditFinding
from doci.tools.delete_finding import build_delete_finding
from doci.tools.list_findings import build_list_findings


class _FakeAudit:
    def __init__(self, findings=None):
        self._findings = list(findings or [])
        self.deleted: list[tuple[UUID, UUID]] = []

    async def list_findings(self, execution_id):
        return list(self._findings)

    async def delete_finding(self, *, execution_id, finding_id):
        self.deleted.append((execution_id, finding_id))
        return True


def _finding(fid: UUID) -> AuditFinding:
    return AuditFinding(
        id=fid,
        execution_id=uuid4(),
        rule_key="R1",
        severity="low",
        status="fail",
        message="m",
        evidence=[],
        created_at=datetime.now(timezone.utc),
    )


def test_list_findings_exposes_id():
    fid = uuid4()
    tool = build_list_findings(_FakeAudit([_finding(fid)]), uuid4())
    out = asyncio.run(tool.ainvoke({}))
    assert out["ok"] is True
    assert out["findings"][0]["id"] == str(fid)


def test_delete_finding_calls_service_with_uuid():
    eid = uuid4()
    fid = uuid4()
    audit = _FakeAudit()
    tool = build_delete_finding(audit, eid)
    out = asyncio.run(tool.ainvoke({"finding_id": str(fid)}))
    assert out["ok"] is True
    assert audit.deleted == [(eid, fid)]


def test_delete_finding_rejects_bad_uuid():
    audit = _FakeAudit()
    tool = build_delete_finding(audit, uuid4())
    out = asyncio.run(tool.ainvoke({"finding_id": "not-a-uuid"}))
    assert out["ok"] is False
    assert audit.deleted == []
