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
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver


@broker.task
async def run_document_mining(media_id: str, execution_id: str, thread_id: str) -> dict:
    """Finalize + classify ``media_id`` and route it through the mining graph.

    Image originals are processed by the image child subgraph; the run is durable
    via the shared Valkey checkpointer (thread = the per-execution ``thread_id``).
    Lifecycle + result are persisted to ``workflow_execution`` via ``execution_id``.
    """
    clients = get_clients()
    runs = clients.workflow_runs
    eid = UUID(execution_id)
    await runs.mark_running(eid)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        # Image child is embedded as a subgraph — compiled without its own
        # checkpointer so the parent's checkpointer persists its state too.
        image_graph = build_image_graph(clients.media)
        graph = build_document_mining_graph(
            finalize=FinalizeMedia(clients.media),
            image_graph=image_graph,
            checkpointer=get_saver(),
        )
        result = await graph.ainvoke({"media_id": UUID(media_id)}, config=config)
        doc_type = result.get("document_type")
        output = {
            "media_id": media_id,
            "document_type": doc_type.value if doc_type is not None else None,
            "mime_type": result.get("mime_type"),
            "unsupported_reason": result.get("unsupported_reason"),
        }
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_succeeded(eid, WorkflowResult(output=output), meta)
        return output
    except Exception as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error=str(exc)), meta)
        raise
