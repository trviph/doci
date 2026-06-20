"""Verdict node: a fresh small agent reads the findings and sets the verdict.

Runs after the find node with its own context + checkpoint sub-thread
(``…:verdict``). Reads only the recorded findings (+ the §7 criteria) and calls
``set_verdict``; returns no state.
"""

import asyncio
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from doci.agents import build_verdict_agent
from doci.workflows.langgraph_audit.state import AuditState
from doci.workflows.tracing import child_config

if TYPE_CHECKING:
    from doci.bootstrap import Clients

VERDICT_TIMEOUT_S = 5 * 60
VERDICT_RECURSION_LIMIT = 60

_KICKOFF = (
    "Review the recorded findings for this dossier and set a single verdict "
    "(pass / needs_review / fail) with a rationale."
)


def make_verdict_node(clients: "Clients", checkpointer: BaseCheckpointSaver | None):
    """Build the verdict node bound to the shared clients + agent checkpointer."""

    async def verdict_node(state: AuditState, config: RunnableConfig) -> dict:
        thread_id = config["configurable"]["thread_id"]
        agent = build_verdict_agent(
            clients=clients,
            audit_execution_id=state["audit_execution_id"],
            dossier_key=state["dossier_key"],
            document_id=state["document_id"],
            checkpointer=checkpointer,
        )
        await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(_KICKOFF)]},
                config=child_config(
                    config,
                    thread_id=f"{thread_id}:verdict",
                    run_name="audit:verdict",
                    recursion_limit=VERDICT_RECURSION_LIMIT,
                    tags=["audit", "phase:verdict"],
                    metadata={
                        "audit_execution_id": str(state["audit_execution_id"]),
                        "dossier_key": state["dossier_key"],
                        "parent_agent": "audit",
                        "depth": 1,
                    },
                ),
            ),
            timeout=VERDICT_TIMEOUT_S,
        )
        return {}

    return verdict_node
