"""TaskIQ entry point for the PDF document-mining child workflow.

Runs standalone for a single **already-READY** PDF document (the child does not
finalize — that's the parent's job). Durable via the shared Valkey checkpointer
(thread = the per-execution ``thread_id``); per-page image runs get their own
sub-threads. Lifecycle + result are persisted to ``workflow_execution`` via
``execution_id``.
"""

import asyncio
from uuid import UUID

from doci.documents import DocumentStatus
from doci.taskiq import broker
from doci.taskiq.retry import TaskTimeout
from doci.workflows.langgraph_document_mining_pdf.deps import build_pdf_graph
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver

# Per-task config: a 15-minute time budget; retry every failure except a timeout.
TIMEOUT_S = 15 * 60
MAX_RETRIES = 3


class DocumentNotReady(Exception):
    """Raised when the child workflow is asked to mine a non-READY document."""


def _page_output(page: dict) -> dict:
    """JSON-safe view of a per-page result (UUIDs → str)."""
    thumb = page.get("thumb_media_id")
    page_media = page.get("page_media_id")
    return {
        "page_number": page.get("page_number"),
        "kind": page.get("kind"),
        "page_media_id": str(page_media) if page_media is not None else None,
        "thumb_media_id": str(thumb) if thumb is not None else None,
        "extract_ref": page.get("extract_ref"),
        "annotation_ref": page.get("annotation_ref"),
    }


@broker.task(retry_on_error=True, max_retries=MAX_RETRIES)
async def run_document_mining_pdf(
    document_id: str, execution_id: str, thread_id: str
) -> dict:
    """Split + per-page extract/annotate/thumbnail a READY PDF ``document_id``.

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

        graph = build_pdf_graph(
            clients.media,
            clients.documents,
            clients.workflow_results,
            checkpointer=get_saver(),
        )
        result = await asyncio.wait_for(
            graph.ainvoke(
                {"media_id": doc.media_id, "document_id": did, "execution_id": eid},
                config={"configurable": {"thread_id": thread_id}},
            ),
            timeout=TIMEOUT_S,
        )
        output = {
            "document_id": document_id,
            "page_count": result.get("page_count"),
            "pages": [_page_output(p) for p in result.get("page_results", [])],
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
