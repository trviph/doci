"""FastAPI router to submit + read audit jobs.

``POST /audits`` enqueues an audit of a document's mined dossier (defaulting to
the document's latest succeeded mining run); ``GET /audits/{id}`` returns the
run's status, verdict, and findings. Resolves ``app.state.workflow_runs`` /
``app.state.audit`` when services are not explicitly bound.
"""

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.audit import AuditService
from doci.workflows.audit.task import run_audit
from doci.workflows.models import (
    LangGraphMeta,
    WorkflowInput,
    WorkflowMetadata,
    WorkflowStatus,
)
from doci.workflows.service import WorkflowExecutionNotFound, WorkflowExecutionService


class SubmitAuditRequest(BaseModel):
    document_id: UUID
    dossier_key: str
    mining_execution_id: UUID | None = Field(
        default=None,
        description="Mining run whose results to audit; defaults to the document's "
        "latest succeeded document_mining run.",
    )


class AuditJobModel(BaseModel):
    execution_id: UUID
    mining_execution_id: UUID
    document_id: UUID
    dossier_key: str


class FindingModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    rule_key: str | None
    severity: str
    status: str
    message: str
    evidence: list[Any]


class AuditReportModel(BaseModel):
    execution_id: UUID
    status: str
    verdict: str | None
    rationale: str | None
    findings: list[FindingModel]


def build_audit_router(
    *,
    runs: WorkflowExecutionService | None = None,
    audit: AuditService | None = None,
) -> APIRouter:
    """Build the /audits APIRouter."""
    r = APIRouter(prefix="/audits", tags=["audit"])

    def _runs(request: Request) -> WorkflowExecutionService:
        return runs if runs is not None else request.app.state.workflow_runs

    def _audit(request: Request) -> AuditService:
        return audit if audit is not None else request.app.state.audit

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Submit an audit job")
    async def submit(
        body: SubmitAuditRequest = Body(...),
        runs_svc: WorkflowExecutionService = Depends(_runs),
    ) -> AuditJobModel:
        mining_eid = body.mining_execution_id
        if mining_eid is None:
            rec = await runs_svc.latest_succeeded(
                body.document_id, workflow="document_mining"
            )
            if rec is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    "no succeeded mining run for this document; pass mining_execution_id",
                )
            mining_eid = rec.id
        thread_id = uuid4()
        execution_id = await runs_svc.create(
            workflow="audit",
            entity_type="document",
            entity_id=body.document_id,
            input=WorkflowInput(
                document_id=body.document_id, dossier_key=body.dossier_key
            ),
            metadata=WorkflowMetadata(langgraph=LangGraphMeta(thread_id=str(thread_id))),
        )
        await run_audit.kiq(
            str(body.document_id),
            str(execution_id),
            str(mining_eid),
            str(thread_id),
            body.dossier_key,
        )
        return AuditJobModel(
            execution_id=execution_id,
            mining_execution_id=mining_eid,
            document_id=body.document_id,
            dossier_key=body.dossier_key,
        )

    @r.get("/{execution_id}", summary="Get an audit's status + findings", responses={404: {}})
    async def get_report(
        execution_id: UUID,
        runs_svc: WorkflowExecutionService = Depends(_runs),
        audit_svc: AuditService = Depends(_audit),
    ) -> AuditReportModel:
        try:
            rec = await runs_svc.get(execution_id)
        except WorkflowExecutionNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        verdict = await audit_svc.get_verdict(execution_id)
        findings = await audit_svc.list_findings(execution_id)
        return AuditReportModel(
            execution_id=execution_id,
            status=WorkflowStatus(rec.status).name,
            verdict=verdict.verdict if verdict else None,
            rationale=verdict.rationale if verdict else None,
            findings=[FindingModel.model_validate(f) for f in findings],
        )

    return r
