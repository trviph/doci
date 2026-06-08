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

from doci.media import MediaNotFound, MediaService
from doci.workflows.langgraph_document_mining.task import run_document_mining
from doci.workflows.langgraph_document_mining_image.task import (
    run_document_mining_image,
)
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


# Workflow -> the taskiq task that runs it. Both take ``media_id: str``.
_TASKS = {
    WorkflowKind.DOCUMENT_MINING: run_document_mining,
    WorkflowKind.IMAGE: run_document_mining_image,
}


class SubmitWorkflowRequest(BaseModel):
    media_id: UUID = Field(description="Media to run the workflow on.")
    workflow: WorkflowKind = Field(
        default=WorkflowKind.DOCUMENT_MINING, description="Which workflow to run."
    )


class WorkflowJobModel(BaseModel):
    execution_id: UUID = Field(description="Persisted workflow_execution row id.")
    task_id: str = Field(description="Enqueued taskiq job id.")
    workflow: WorkflowKind
    media_id: UUID


def build_workflows_router(
    media: MediaService | None = None,
    runs: WorkflowExecutionService | None = None,
) -> APIRouter:
    """Build the workflows APIRouter.

    Resolves `app.state.media` / `app.state.workflow_runs` when not bound.
    """
    router = APIRouter(prefix="/workflows", tags=["workflows"])

    def _media(request: Request) -> MediaService:
        return media if media is not None else request.app.state.media

    def _runs(request: Request) -> WorkflowExecutionService:
        return runs if runs is not None else request.app.state.workflow_runs

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Submit a workflow job for a media",
        responses={404: {}},
    )
    async def submit(
        body: SubmitWorkflowRequest = Body(...),
        svc: MediaService = Depends(_media),
        runs: WorkflowExecutionService = Depends(_runs),
    ) -> WorkflowJobModel:
        try:
            await svc.get(body.media_id)
        except MediaNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

        # Fresh per-execution LangGraph thread; record the run before enqueuing so
        # the worker can never reference a row that doesn't exist yet.
        thread_id = uuid4()
        execution_id = await runs.create(
            workflow=body.workflow.value,
            entity_type="media",
            entity_id=body.media_id,
            input=WorkflowInput(media_id=body.media_id),
            metadata=WorkflowMetadata(
                langgraph=LangGraphMeta(thread_id=str(thread_id))
            ),
        )
        task = await _TASKS[body.workflow].kiq(
            str(body.media_id), str(execution_id), str(thread_id)
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
            media_id=body.media_id,
        )

    return router
