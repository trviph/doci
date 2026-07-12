"""Audit graph gains a reflect (consolidation) phase: find → reflect → verdict."""

import asyncio
from uuid import uuid4

import doci.workflows.langgraph_audit.nodes.reflect as reflect_mod
from doci.workflows.langgraph_audit.graph import build_audit_graph
from doci.workflows.langgraph_audit.nodes.reflect import make_reflect_node


def test_graph_runs_reflect_between_find_and_verdict():
    graph = build_audit_graph(clients=object())
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("find", "reflect") in edges
    assert ("reflect", "verdict") in edges
    # the old direct find→verdict edge must be gone
    assert ("find", "verdict") not in edges


def test_reflect_node_invokes_agent_on_reflect_subthread(monkeypatch):
    captured = {}

    class _FakeAgent:
        async def ainvoke(self, payload, config):
            captured["thread_id"] = config["configurable"]["thread_id"]
            captured["tags"] = config.get("tags")
            return {}

    def _fake_build(**kwargs):
        captured["mining_execution_id"] = kwargs["mining_execution_id"]
        captured["audit_execution_id"] = kwargs["audit_execution_id"]
        return _FakeAgent()

    monkeypatch.setattr(reflect_mod, "build_reflection_agent", _fake_build)

    node = make_reflect_node(clients=object(), checkpointer=None)
    mining, audit = uuid4(), uuid4()
    out = asyncio.run(
        node(
            {
                "mining_execution_id": mining,
                "audit_execution_id": audit,
                "dossier_key": "d",
            },
            {"configurable": {"thread_id": "t"}},
        )
    )
    assert out == {}
    assert captured["thread_id"] == "t:reflect"
    assert "phase:reflect" in captured["tags"]
    assert captured["mining_execution_id"] == mining
    assert captured["audit_execution_id"] == audit
