"""TaskIQ entry point for the audit workflow (two phases, fresh context each).

Phase 1 (finding): the orchestrator + rule subagents investigate the document's
mined results and record findings. Phase 2 (verdict): a separate small agent — a
*fresh* invocation with its own context — reads only the recorded findings and
sets the dossier verdict. Splitting them keeps each context small (the monolithic
single-phase agent timed out before reaching a verdict). Clients come from
``broker.state``; findings/verdict are persisted by the agents' tools.
"""

import asyncio
from uuid import UUID

from langchain_core.messages import HumanMessage

from doci.agents import build_finding_agent, build_verdict_agent
from doci.taskiq import broker
from doci.taskiq.retry import TaskTimeout
from doci.workflows.models import WorkflowResult
from doci.workflows.runtime import final_metadata, get_clients, get_saver

# Per-phase budgets + graph-step limits. The finding phase delegates a subagent
# per rule (or per group), so it gets the bigger budget; the verdict phase reads
# a compact list and concludes, so it is short.
FINDING_TIMEOUT_S = 25 * 60
VERDICT_TIMEOUT_S = 5 * 60
FINDING_RECURSION_LIMIT = 400
VERDICT_RECURSION_LIMIT = 60
MAX_RETRIES = 1

_FIND_KICKOFF = (
    "Investigate this payment dossier from its mined data: check completeness and "
    "evaluate every applicable rule (delegating to the rule_auditor subagent), "
    "recording your findings. Do not set a verdict."
)
_VERDICT_KICKOFF = (
    "Review the recorded findings for this dossier and set a single verdict "
    "(pass / needs_review / fail) with a rationale."
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
        await clients.audit.clear(eid)  # idempotent: a retry starts clean

        # Phase 1 — finding (own context / checkpoint thread)
        finder = build_finding_agent(
            clients=clients,
            mining_execution_id=UUID(mining_execution_id),
            audit_execution_id=eid,
            dossier_key=dossier_key,
            checkpointer=get_saver(),
        )
        await asyncio.wait_for(
            finder.ainvoke(
                {"messages": [HumanMessage(_FIND_KICKOFF)]},
                config={
                    "configurable": {"thread_id": f"{thread_id}:find"},
                    "recursion_limit": FINDING_RECURSION_LIMIT,
                },
            ),
            timeout=FINDING_TIMEOUT_S,
        )

        # Phase 2 — verdict (separate fresh context / checkpoint thread)
        verdicter = build_verdict_agent(
            clients=clients,
            audit_execution_id=eid,
            dossier_key=dossier_key,
            document_id=UUID(document_id),
            checkpointer=get_saver(),
        )
        await asyncio.wait_for(
            verdicter.ainvoke(
                {"messages": [HumanMessage(_VERDICT_KICKOFF)]},
                config={
                    "configurable": {"thread_id": f"{thread_id}:verdict"},
                    "recursion_limit": VERDICT_RECURSION_LIMIT,
                },
            ),
            timeout=VERDICT_TIMEOUT_S,
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
        await runs.mark_failed(eid, WorkflowResult(error="audit phase timed out"), meta)
        raise TaskTimeout(audit_execution_id) from exc
    except Exception as exc:
        meta = await final_metadata(runs, eid, thread_id)
        await runs.mark_failed(eid, WorkflowResult(error=str(exc)), meta)
        raise
