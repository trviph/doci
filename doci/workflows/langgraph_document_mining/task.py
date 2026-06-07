"""TaskIQ entry point for the document-mining workflow.

The worker has no FastAPI lifespan, so the shared clients are built once on
``WORKER_STARTUP`` (and released on shutdown) and stashed on ``broker.state``,
mirroring the API's lifespan (:mod:`doci.api.app`). The task reads them from
there, builds the graph, and runs it for a single media.
"""

from uuid import UUID

from taskiq import TaskiqEvents, TaskiqState

from doci.activities import FinalizeMedia
from doci.bootstrap import Clients, build_clients, close_clients
from doci.taskiq import broker
from doci.workflows.langgraph_document_mining.graph import (
    build_document_mining_graph,
)

#: Attribute under which the shared clients live on ``broker.state``.
_CLIENTS_ATTR = "doci_clients"


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _build_clients(state: TaskiqState) -> None:
    setattr(state, _CLIENTS_ATTR, build_clients())


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _close_clients(state: TaskiqState) -> None:
    clients: Clients | None = getattr(state, _CLIENTS_ATTR, None)
    if clients is not None:
        await close_clients(clients)


@broker.task
async def run_document_mining(media_id: str) -> dict:
    """Finalize + classify ``media_id`` through the document-mining graph."""
    clients: Clients = getattr(broker.state, _CLIENTS_ATTR)
    graph = build_document_mining_graph(finalize=FinalizeMedia(clients.media))
    result = await graph.ainvoke({"media_id": UUID(media_id)})
    doc_type = result.get("document_type")
    return {
        "media_id": media_id,
        "document_type": doc_type.value if doc_type is not None else None,
        "mime_type": result.get("mime_type"),
        "unsupported_reason": result.get("unsupported_reason"),
    }
