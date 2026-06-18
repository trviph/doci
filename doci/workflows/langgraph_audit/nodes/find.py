"""Find node: the finding agent investigates and records findings.

Clears any prior results for this run, then runs the finding deep agent under its
own budget + checkpoint sub-thread (``…:find``). Findings persist as a side
effect (the agent's ``record_finding`` tool); the node returns no state.
"""

import asyncio
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from doci.agents import build_finding_agent
from doci.workflows.langgraph_audit.state import AuditState

if TYPE_CHECKING:
    from doci.bootstrap import Clients

FINDING_TIMEOUT_S = 25 * 60
FINDING_RECURSION_LIMIT = 400

_KICKOFF = (
    "Investigate this payment dossier from its mined data: check completeness and "
    "evaluate every applicable rule (delegating to the rule_auditor subagent), "
    "recording your findings. Do not set a verdict."
)


def make_find_node(clients: "Clients", checkpointer: BaseCheckpointSaver | None):
    """Build the find node bound to the shared clients + agent checkpointer."""

    async def find_node(state: AuditState, config: RunnableConfig) -> dict:
        thread_id = config["configurable"]["thread_id"]
        eid = state["audit_execution_id"]
        await clients.audit.clear(eid)  # idempotent: a resumed/retried run starts clean
        agent = build_finding_agent(
            clients=clients,
            mining_execution_id=state["mining_execution_id"],
            audit_execution_id=eid,
            dossier_key=state["dossier_key"],
            checkpointer=checkpointer,
        )
        await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(_KICKOFF)]},
                config={
                    "configurable": {"thread_id": f"{thread_id}:find"},
                    "recursion_limit": FINDING_RECURSION_LIMIT,
                },
            ),
            timeout=FINDING_TIMEOUT_S,
        )
        return {}

    return find_node
