"""Compose the audit workflow as a LangGraph graph.

A three-node chain — investigate, consolidate, then conclude:

    START → find → reflect → verdict → END

Each node wraps a deepagents agent (finding / verdict) run with its own context.
Built with pure DI (the shared ``clients``); the compiled graph is reusable — a
task invokes it, and another workflow could embed it as a subgraph. Pass a
``checkpointer`` for durable runs (threaded down to the agents too).
"""

from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from doci.workflows.langgraph_audit.nodes import (
    make_find_node,
    make_reflect_node,
    make_verdict_node,
)
from doci.workflows.langgraph_audit.state import AuditState

if TYPE_CHECKING:
    from doci.bootstrap import Clients


def build_audit_graph(
    clients: "Clients", *, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Build + compile the audit graph (find → reflect → verdict) over the shared
    clients."""
    g = StateGraph(AuditState)
    g.add_node("find", make_find_node(clients, checkpointer))
    g.add_node("reflect", make_reflect_node(clients, checkpointer))
    g.add_node("verdict", make_verdict_node(clients, checkpointer))

    g.add_edge(START, "find")
    g.add_edge("find", "reflect")
    g.add_edge("reflect", "verdict")
    g.add_edge("verdict", END)
    return g.compile(checkpointer=checkpointer)
