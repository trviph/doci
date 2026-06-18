"""TaskIQ entry point for the audit workflow.

Runs the deepagents audit agent (:func:`build_audit_agent`) over a document's
mined results for a dossier, then records the verdict on the audit
``workflow_execution`` row. Mirrors the mining tasks: clients are read from
``broker.state`` (built at worker startup); the agent persists findings/verdict
as a side effect via its tools, so the result here is just a summary.
"""

import asyncio
from uuid import UUID

from langchain_core.messages import HumanMessage

from doci.agents import build_audit_agent
from doci.taskiq import broker
from doci.taskiq.retry import TaskTimeout
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver

TIMEOUT_S = 20 * 60
MAX_RETRIES = 1
# The orchestrator delegates to a subagent per rule, each making several tool
# calls — give the run plenty of graph steps.
RECURSION_LIMIT = 300

_KICKOFF = (
    "Audit this payment dossier from its mined data: check completeness, evaluate "
    "every applicable rule (delegating each to the rule_auditor subagent), record "
    "your findings, and set a single verdict."
)


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
        agent = build_audit_agent(
            clients=clients,
            mining_execution_id=UUID(mining_execution_id),
            audit_execution_id=eid,
            dossier_key=dossier_key,
            document_id=UUID(document_id),
            checkpointer=get_saver(),
        )
        await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(_KICKOFF)]},
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": RECURSION_LIMIT,
                },
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
        await runs.mark_failed(
            eid, WorkflowResult(error=f"timed out after {TIMEOUT_S}s"), meta
        )
        raise TaskTimeout(audit_execution_id) from exc
    except Exception as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error=str(exc)), meta)
        raise
