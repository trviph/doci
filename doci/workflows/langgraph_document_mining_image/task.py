"""TaskIQ entry point for the image document-mining child workflow.

Runs standalone for a single **already-READY** image media (the child does not
finalize — that's the parent's job). Durable via the shared Valkey checkpointer
(thread = the per-execution ``thread_id``). Worker-side clients + checkpointer
come from :mod:`doci.workflows.runtime`. Lifecycle + result are persisted to
``workflow_execution`` via ``execution_id``.
"""

from uuid import UUID

from doci.media import MediaStatus
from doci.taskiq import broker
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver


class MediaNotReady(Exception):
    """Raised when the child workflow is asked to mine a non-READY media."""


@broker.task
async def run_document_mining_image(
    media_id: str, execution_id: str, thread_id: str
) -> dict:
    """Thumbnail + extract + annotate a READY image ``media_id``."""
    mid = UUID(media_id)
    clients = get_clients()
    runs = clients.workflow_runs
    eid = UUID(execution_id)
    await runs.mark_running(eid)
    try:
        rec = await clients.media.get(mid)
        if rec.status is not MediaStatus.READY:
            raise MediaNotReady(f"{media_id} is {rec.status.name}, expected READY")

        graph = build_image_graph(clients.media, checkpointer=get_saver())
        result = await graph.ainvoke(
            {"media_id": mid},
            config={"configurable": {"thread_id": thread_id}},
        )
        thumb = result.get("thumb_media_id")
        output = {
            "media_id": media_id,
            "thumb_media_id": str(thumb) if thumb is not None else None,
            "extract_ref": result.get("extract_ref"),
            "annotation_ref": result.get("annotation_ref"),
        }
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_succeeded(eid, WorkflowResult(output=output), meta)
        return output
    except Exception as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error=str(exc)), meta)
        raise
