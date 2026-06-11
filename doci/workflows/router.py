"""FastAPI router to submit document-mining workflow jobs.

Mirrors the media router: pass a ``MediaService`` to bind it, or omit it to
resolve ``request.app.state.media`` at request time. Submitting enqueues a taskiq
job and returns its id; the broker has no result backend, so this is
submit-only (no status/result retrieval here).
"""

from enum import Enum
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
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
)
from doci.workflows.service import WorkflowExecutionService


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
    group_key: str | None = Field(
        default=None,
        description="Optional dossier group key; annotate classifies each page "
        "against the group's document types and extracts their fields.",
    )


class WorkflowJobModel(BaseModel):
    execution_id: UUID = Field(description="Persisted workflow_execution row id.")
    task_id: str = Field(description="Enqueued taskiq job id.")
    workflow: WorkflowKind
    document_id: UUID


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
            input=WorkflowInput(document_id=body.document_id, group_key=body.group_key),
            metadata=WorkflowMetadata(
                langgraph=LangGraphMeta(thread_id=str(thread_id))
            ),
        )
        task = await _TASKS[body.workflow].kiq(
            str(body.document_id),
            str(execution_id),
            str(thread_id),
            body.group_key,
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

    return router
