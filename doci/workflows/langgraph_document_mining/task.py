"""TaskIQ entry point for the document-mining workflow.

The worker has no FastAPI lifespan, so the shared clients are built once on
``WORKER_STARTUP`` (and released on shutdown) and stashed on ``broker.state``,
mirroring the API's lifespan (:mod:`doci.api.app`). The task reads them from
there, builds the graph, and runs it for a single media.
"""

from uuid import UUID

from doci.activities import FinalizeMedia
from doci.taskiq import broker
from doci.workflows.langgraph_document_mining.graph import (
    build_document_mining_graph,
)
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.runtime import get_clients, get_saver


@broker.task
async def run_document_mining(media_id: str) -> dict:
    """Finalize + classify ``media_id`` and route it through the mining graph.

    Image originals are processed by the image child subgraph; the run is durable
    via the shared Valkey checkpointer (thread = the media id).
    """
    clients = get_clients()
    # Image child is embedded as a subgraph — compiled without its own
    # checkpointer so the parent's checkpointer persists its state too.
    image_graph = build_image_graph(clients.media)
    graph = build_document_mining_graph(
        finalize=FinalizeMedia(clients.media),
        image_graph=image_graph,
        checkpointer=get_saver(),
    )
    result = await graph.ainvoke(
        {"media_id": UUID(media_id)},
        config={"configurable": {"thread_id": str(media_id)}},
    )
    doc_type = result.get("document_type")
    return {
        "media_id": media_id,
        "document_type": doc_type.value if doc_type is not None else None,
        "mime_type": result.get("mime_type"),
        "unsupported_reason": result.get("unsupported_reason"),
    }
