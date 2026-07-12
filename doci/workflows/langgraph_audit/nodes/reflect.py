"""Reflect node: a fresh agent consolidates the findings before the verdict.

Runs after the find node with its own context + checkpoint sub-thread
(``…:reflect``). Reads the recorded findings, dedups/reconciles them (deleting
duplicates and the wrong side of contradictions, merging fragments), and returns
no state. Bounded by its own timeout + recursion limit so a runaway
consolidation loop can never hang the run.
"""

import asyncio
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from doci.agents import build_reflection_agent
from doci.workflows.langgraph_audit.state import AuditState
from doci.workflows.tracing import child_config

if TYPE_CHECKING:
    from doci.bootstrap import Clients

REFLECT_TIMEOUT_S = 5 * 60
REFLECT_RECURSION_LIMIT = 60

_KICKOFF = (
    "Review the findings recorded for this dossier and consolidate them: delete "
    "exact duplicates, reconcile contradictions against the evidence, and merge "
    "fragments of one issue. Make one pass, then stop. Do not set a verdict."
)


def make_reflect_node(clients: "Clients", checkpointer: BaseCheckpointSaver | None):
    """Build the reflect node bound to the shared clients + agent checkpointer."""

    async def reflect_node(state: AuditState, config: RunnableConfig) -> dict:
        thread_id = config["configurable"]["thread_id"]
        agent = build_reflection_agent(
            clients=clients,
            mining_execution_id=state["mining_execution_id"],
            audit_execution_id=state["audit_execution_id"],
            language=state.get("language", "English"),
            checkpointer=checkpointer,
        )
        await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(_KICKOFF)]},
                config=child_config(
                    config,
                    thread_id=f"{thread_id}:reflect",
                    run_name="audit:reflect",
                    recursion_limit=REFLECT_RECURSION_LIMIT,
                    tags=["audit", "phase:reflect"],
                    metadata={
                        "audit_execution_id": str(state["audit_execution_id"]),
                        "dossier_key": state["dossier_key"],
                        "parent_agent": "audit",
                        "depth": 1,
                    },
                ),
            ),
            timeout=REFLECT_TIMEOUT_S,
        )
        return {}

    return reflect_node
