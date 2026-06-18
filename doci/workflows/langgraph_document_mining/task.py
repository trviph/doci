"""TaskIQ entry point for the document-mining workflow.

The worker has no FastAPI lifespan, so the shared clients are built once on
``WORKER_STARTUP`` (and released on shutdown) and stashed on ``broker.state``,
mirroring the API's lifespan (:mod:`doci.api.app`). The task reads them from
there, builds the graph, and runs it for a single media.
"""

import asyncio
from uuid import UUID

from doci.activities import FinalizeDocument
from doci.taskiq import broker
from doci.taskiq.retry import TaskTimeout
from doci.workflows.audit.trigger import enqueue_audit
from doci.workflows.langgraph_document_mining.graph import (
    build_document_mining_graph,
)
from doci.workflows.dossierspec import resolve_dossier_spec
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.langgraph_document_mining_pdf.deps import build_pdf_graph
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver

# Per-task config: a 15-minute time budget; retry every failure except a timeout.
TIMEOUT_S = 15 * 60
MAX_RETRIES = 3


@broker.task(retry_on_error=True, max_retries=MAX_RETRIES)
async def run_document_mining(
    document_id: str, execution_id: str, thread_id: str, dossier_key: str | None = None
) -> dict:
    """Finalize + classify ``document_id`` and route it through the mining graph.

    Image originals are processed by the image child subgraph; the run is durable
    via the shared Valkey checkpointer (thread = the per-execution ``thread_id``).
    Lifecycle + result are persisted to ``workflow_execution`` via ``execution_id``.
    Runs under a ``TIMEOUT_S`` budget; failures retry (``MAX_RETRIES``) except a
    timeout, which fails terminally.
    """
    clients = get_clients()
    runs = clients.workflow_runs
    eid = UUID(execution_id)
    await runs.mark_running(eid)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        # Child graphs are embedded as structural subgraph nodes — compiled
        # without their own checkpointer so the parent's checkpointer (below)
        # persists their state. (build_pdf_graph forwards that None to the image
        # graph it invokes per page; those per-page runs re-run on a retry, the
        # same node-granularity the image branch has.)
        image_graph = build_image_graph(clients.media, clients.workflow_results)
        pdf_graph = build_pdf_graph(
            clients.media, clients.documents, clients.workflow_results
        )
        graph = build_document_mining_graph(
            finalize=FinalizeDocument(clients.documents),
            documents=clients.documents,
            image_graph=image_graph,
            pdf_graph=pdf_graph,
            checkpointer=get_saver(),
        )
        dossier_spec = await resolve_dossier_spec(
            clients.userdata_dossier_defs, clients.userdata_document_defs, dossier_key
        )
        result = await asyncio.wait_for(
            graph.ainvoke(
                {
                    "document_id": UUID(document_id),
                    "execution_id": eid,
                    "dossier_spec": dossier_spec,
                },
                config=config,
            ),
            timeout=TIMEOUT_S,
        )
        doc_type = result.get("document_type")
        output = {
            "document_id": document_id,
            "document_type": doc_type.value if doc_type is not None else None,
            "mime_type": result.get("mime_type"),
            "unsupported_reason": result.get("unsupported_reason"),
        }
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_succeeded(eid, WorkflowResult(output=output), meta)
        # Auto-chain an audit of this exact mining run when a dossier was given.
        if dossier_key:
            await enqueue_audit(
                runs,
                document_id=UUID(document_id),
                mining_execution_id=eid,
                dossier_key=dossier_key,
            )
        return output
    except TimeoutError as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(
            eid, WorkflowResult(error=f"timed out after {TIMEOUT_S}s"), meta
        )
        raise TaskTimeout(execution_id) from exc
    except Exception as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error=str(exc)), meta)
        raise
