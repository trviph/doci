"""TaskIQ entry point for the audit workflow.

Runs the audit graph (find → verdict) over a document's mined results for a
dossier. Mirrors the mining tasks: the shared clients are read from
``broker.state``; the task builds the graph and invokes it. Findings + verdict
are persisted by the graph's nodes (via the agents' tools), so the result here is
just a summary.
"""

import asyncio
from uuid import UUID

from doci.taskiq import broker
from doci.taskiq.retry import TaskTimeout
from doci.workflows.langgraph_audit.graph import build_audit_graph
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver

# Overall budget covering both phases; each node also enforces its own per-phase
# timeout (see the find / verdict nodes).
TIMEOUT_S = 35 * 60
MAX_RETRIES = 1


@broker.task(retry_on_error=True, max_retries=MAX_RETRIES)
async def run_audit(
    document_id: str,
    audit_execution_id: str,
    mining_execution_id: str,
    thread_id: str,
    dossier_key: str,
) -> dict:
    """Audit ``document_id`` for ``dossier_key`` against its mined results."""
    clients = get_clients()
    runs = clients.workflow_runs
    eid = UUID(audit_execution_id)
    await runs.mark_running(eid)
    try:
        graph = build_audit_graph(clients, checkpointer=get_saver())
        await asyncio.wait_for(
            graph.ainvoke(
                {
                    "document_id": UUID(document_id),
                    "mining_execution_id": UUID(mining_execution_id),
                    "audit_execution_id": eid,
                    "dossier_key": dossier_key,
                },
                config={"configurable": {"thread_id": thread_id}},
            ),
            timeout=TIMEOUT_S,
        )
        verdict = await clients.audit.get_verdict(eid)
        findings = await clients.audit.list_findings(eid)
        output = {
            "document_id": document_id,
            "dossier_key": dossier_key,
            "verdict": verdict.verdict if verdict else None,
            "finding_count": len(findings),
        }
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_succeeded(eid, WorkflowResult(output=output), meta)
        return output
    except TimeoutError as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error="audit timed out"), meta)
        raise TaskTimeout(audit_execution_id) from exc
    except Exception as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error=str(exc)), meta)
        raise
