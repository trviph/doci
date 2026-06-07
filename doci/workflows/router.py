"""FastAPI router to submit document-mining workflow jobs.

Mirrors the media router: pass a ``MediaService`` to bind it, or omit it to
resolve ``request.app.state.media`` at request time. Submitting enqueues a taskiq
job and returns its id; the broker has no result backend, so this is
submit-only (no status/result retrieval here).
"""

from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from doci.media import MediaNotFound, MediaService
from doci.workflows.langgraph_document_mining.task import run_document_mining
from doci.workflows.langgraph_document_mining_image.task import (
    run_document_mining_image,
)


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
    task_id: str = Field(description="Enqueued taskiq job id.")
    workflow: WorkflowKind
    media_id: UUID


def build_workflows_router(media: MediaService | None = None) -> APIRouter:
    """Build the workflows APIRouter. Resolves `app.state.media` when not bound."""
    router = APIRouter(prefix="/workflows", tags=["workflows"])

    def _svc(request: Request) -> MediaService:
        return media if media is not None else request.app.state.media

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Submit a workflow job for a media",
        responses={404: {}},
    )
    async def submit(
        body: SubmitWorkflowRequest = Body(...), svc: MediaService = Depends(_svc)
    ) -> WorkflowJobModel:
        try:
            await svc.get(body.media_id)
        except MediaNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        task = await _TASKS[body.workflow].kiq(str(body.media_id))
        return WorkflowJobModel(
            task_id=task.task_id, workflow=body.workflow, media_id=body.media_id
        )

    return router