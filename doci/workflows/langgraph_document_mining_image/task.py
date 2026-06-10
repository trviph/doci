"""TaskIQ entry point for the image document-mining child workflow.

Runs standalone for a single **already-READY** image document (the child does not
finalize — that's the parent's job). Durable via the shared Valkey checkpointer
(thread = the per-execution ``thread_id``). Worker-side clients + checkpointer
come from :mod:`doci.workflows.runtime`. Lifecycle + result are persisted to
``workflow_execution`` via ``execution_id``.
"""

import asyncio
from uuid import UUID

from doci.documents import DocumentStatus
from doci.taskiq import broker
from doci.taskiq.retry import TaskTimeout
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver

# Per-task config: a 15-minute time budget; retry every failure except a timeout.
TIMEOUT_S = 15 * 60
MAX_RETRIES = 3


class DocumentNotReady(Exception):
    """Raised when the child workflow is asked to mine a non-READY document."""


@broker.task(retry_on_error=True, max_retries=MAX_RETRIES)
async def run_document_mining_image(
    document_id: str, execution_id: str, thread_id: str
) -> dict:
    """Thumbnail + extract + annotate a READY image ``document_id``.

    Runs under a ``TIMEOUT_S`` budget; failures retry (``MAX_RETRIES``) except a
    timeout, which fails terminally.
    """
    did = UUID(document_id)
    clients = get_clients()
    runs = clients.workflow_runs
    eid = UUID(execution_id)
    await runs.mark_running(eid)
    try:
        doc = await clients.documents.get(did)
        if doc.status is not DocumentStatus.READY:
            raise DocumentNotReady(
                f"{document_id} is {doc.status.name}, expected READY"
            )

        graph = build_image_graph(clients.media, checkpointer=get_saver())
        result = await asyncio.wait_for(
            graph.ainvoke(
                {"media_id": doc.media_id, "document_id": did, "execution_id": eid},
                config={"configurable": {"thread_id": thread_id}},
            ),
            timeout=TIMEOUT_S,
        )
        thumb = result.get("thumb_media_id")
        if thumb is not None:
            await clients.documents.set_document_thumb(did, thumb)
        output = {
            "document_id": document_id,
            "thumb_media_id": str(thumb) if thumb is not None else None,
            "extract_ref": result.get("extract_ref"),
            "annotation_ref": result.get("annotation_ref"),
        }
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_succeeded(eid, WorkflowResult(output=output), meta)
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
