"""FastAPI router to submit document-mining workflow jobs.

Mirrors the media router: pass a ``MediaService`` to bind it, or omit it to
resolve ``request.app.state.media`` at request time. Submitting enqueues a taskiq
job and returns its id; the broker has no result backend, so this is
submit-only (no status/result retrieval here).
"""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from doci.documents import DocumentNotFound, DocumentService
from doci.workflows.langgraph_document_mining.task import run_document_mining
from doci.workflows.langgraph_document_mining_image.task import (
    run_document_mining_image,
)
from doci.workflows.langgraph_document_mining_pdf.task import run_document_mining_pdf
from doci.workflows.models import (
    LangGraphMeta,
    TaskiqMeta,
    WorkflowInput,
    WorkflowMetadata,
    WorkflowStatus,
)
from doci.workflows.service import (
    WorkflowExecutionNotFound,
    WorkflowExecutionService,
)


class WorkflowKind(str, Enum):
    """Which workflow to run for the submitted media."""

    DOCUMENT_MINING = "document_mining"  # parent: finalize → classify → route
    IMAGE = "image"  # child: thumbnail + extract + annotate (requires READY)
    PDF = "pdf"  # child: split → per-page extract/annotate/thumbnail (requires READY)


# Workflow -> the taskiq task that runs it. All take ``media_id: str``.
_TASKS = {
    WorkflowKind.DOCUMENT_MINING: run_document_mining,
    WorkflowKind.IMAGE: run_document_mining_image,
    WorkflowKind.PDF: run_document_mining_pdf,
}


class SubmitWorkflowRequest(BaseModel):
    document_id: UUID = Field(description="Document to run the workflow on.")
    workflow: WorkflowKind = Field(
        default=WorkflowKind.DOCUMENT_MINING, description="Which workflow to run."
    )
    dossier_key: str | None = Field(
        default=None,
        description="Optional dossier key; annotate classifies each page against "
        "the dossier's document types and extracts the facts their look_for calls out.",
    )
    annotate_reflect: bool = Field(
        default=False,
        description="Run the annotation reflection pass (a second LLM critique+revise "
        "of each page's labels/facts). Only takes effect when the server enables it "
        "via DOCI_ANNOTATE_REFLECT; ignored otherwise.",
    )


class WorkflowJobModel(BaseModel):
    execution_id: UUID = Field(description="Persisted workflow_execution row id.")
    task_id: str = Field(description="Enqueued taskiq job id.")
    workflow: WorkflowKind
    document_id: UUID


class WorkflowStatusModel(BaseModel):
    execution_id: UUID = Field(description="The workflow_execution row id.")
    workflow: str = Field(description="Which workflow ran (e.g. document_mining).")
    document_id: UUID = Field(description="The document the run is for.")
    status: str = Field(
        description="QUEUED | RUNNING | SUCCEEDED | FAILED.",
    )
    running: bool = Field(description="True while the run is queued or in progress.")
    error: str | None = Field(
        default=None, description="Failure detail when status is FAILED."
    )
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class WorkflowListItemModel(BaseModel):
    execution_id: UUID = Field(description="The workflow_execution row id.")
    workflow: str = Field(description="Which workflow ran.")
    document_id: UUID = Field(description="The document the run is for.")
    document_name: str | None = Field(
        default=None, description="Name of that document, if any."
    )
    status: str = Field(description="QUEUED | RUNNING | SUCCEEDED | FAILED.")
    running: bool = Field(description="True while queued or in progress.")
    created_at: datetime
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class WorkflowListPageModel(BaseModel):
    items: list[WorkflowListItemModel]
    limit: int
    offset: int
    has_more: bool = Field(description="Whether more rows exist past this page.")


def list_item_from_row(row: dict) -> WorkflowListItemModel:
    """Shape a ``list_recent`` row into a list item (shared by /workflows + /audits)."""
    st = WorkflowStatus(row["status"])
    return WorkflowListItemModel(
        execution_id=row["id"],
        workflow=row["workflow"],
        document_id=row["entity_id"],
        document_name=row["document_name"],
        status=st.name,
        running=st in (WorkflowStatus.QUEUED, WorkflowStatus.RUNNING),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def build_workflows_router(
    documents: DocumentService | None = None,
    runs: WorkflowExecutionService | None = None,
) -> APIRouter:
    """Build the workflows APIRouter.

    Resolves `app.state.documents` / `app.state.workflow_runs` when not bound.
    """
    router = APIRouter(prefix="/workflows", tags=["workflows"])

    def _documents(request: Request) -> DocumentService:
        return documents if documents is not None else request.app.state.documents

    def _runs(request: Request) -> WorkflowExecutionService:
        return runs if runs is not None else request.app.state.workflow_runs

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Submit a workflow job for a document",
        responses={404: {}},
    )
    async def submit(
        body: SubmitWorkflowRequest = Body(...),
        svc: DocumentService = Depends(_documents),
        runs: WorkflowExecutionService = Depends(_runs),
    ) -> WorkflowJobModel:
        try:
            await svc.get(body.document_id)
        except DocumentNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

        # Fresh per-execution LangGraph thread; record the run before enqueuing so
        # the worker can never reference a row that doesn't exist yet.
        thread_id = uuid4()
        execution_id = await runs.create(
            workflow=body.workflow.value,
            entity_type="document",
            entity_id=body.document_id,
            input=WorkflowInput(
                document_id=body.document_id,
                dossier_key=body.dossier_key,
                annotate_reflect=body.annotate_reflect,
            ),
            metadata=WorkflowMetadata(
                langgraph=LangGraphMeta(thread_id=str(thread_id))
            ),
        )
        task = await _TASKS[body.workflow].kiq(
            str(body.document_id),
            str(execution_id),
            str(thread_id),
            body.dossier_key,
            body.annotate_reflect,
        )
        await runs.set_metadata(
            execution_id,
            WorkflowMetadata(
                taskiq=TaskiqMeta(task_id=task.task_id),
                langgraph=LangGraphMeta(thread_id=str(thread_id)),
            ),
        )
        return WorkflowJobModel(
            execution_id=execution_id,
            task_id=task.task_id,
            workflow=body.workflow,
            document_id=body.document_id,
        )

    @router.get("", summary="List workflow runs (newest first, paged)")
    async def list_runs(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        runs: WorkflowExecutionService = Depends(_runs),
    ) -> WorkflowListPageModel:
        # Fetch one extra row to tell whether a next page exists.
        rows = await runs.list_recent(limit=limit + 1, offset=offset)
        has_more = len(rows) > limit
        items = [list_item_from_row(r) for r in rows[:limit]]
        return WorkflowListPageModel(
            items=items, limit=limit, offset=offset, has_more=has_more
        )

    @router.get(
        "/{execution_id}",
        summary="Get a workflow run's status",
        responses={404: {}},
    )
    async def get_status(
        execution_id: UUID, runs: WorkflowExecutionService = Depends(_runs)
    ) -> WorkflowStatusModel:
        try:
            rec = await runs.get(execution_id)
        except WorkflowExecutionNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return WorkflowStatusModel(
            execution_id=rec.id,
            workflow=rec.workflow,
            document_id=rec.entity_id,
            status=WorkflowStatus(rec.status).name,
            running=rec.status in (WorkflowStatus.QUEUED, WorkflowStatus.RUNNING),
            error=rec.result.error if rec.result else None,
            started_at=rec.started_at,
            finished_at=rec.finished_at,
        )

    return router
