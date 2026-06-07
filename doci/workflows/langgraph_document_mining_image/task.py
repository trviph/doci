"""TaskIQ entry point for the image document-mining child workflow.

Runs standalone for a single **already-READY** image media (the child does not
finalize — that's the parent's job). Durable via the shared Valkey checkpointer
(thread = ``image:{media_id}``). Worker-side clients + checkpointer come from
:mod:`doci.workflows.runtime`.
"""

from uuid import UUID

from doci.media import MediaStatus
from doci.taskiq import broker
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.runtime import get_clients, get_saver


class MediaNotReady(Exception):
    """Raised when the child workflow is asked to mine a non-READY media."""


@broker.task
async def run_document_mining_image(media_id: str) -> dict:
    """Thumbnail + extract + annotate a READY image ``media_id``."""
    mid = UUID(media_id)
    clients = get_clients()

    rec = await clients.media.get(mid)
    if rec.status is not MediaStatus.READY:
        raise MediaNotReady(f"{media_id} is {rec.status.name}, expected READY")

    graph = build_image_graph(clients.media, checkpointer=get_saver())
    result = await graph.ainvoke(
        {"media_id": mid},
        config={"configurable": {"thread_id": f"image:{media_id}"}},
    )
    thumb = result.get("thumb_media_id")
    return {
        "media_id": media_id,
        "thumb_media_id": str(thumb) if thumb is not None else None,
        "extract_ref": result.get("extract_ref"),
        "annotation_ref": result.get("annotation_ref"),
    }
