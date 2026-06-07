"""Compose the document-mining workflow as a LangGraph ``StateGraph``.

Entry node finalizes + classifies; a conditional edge routes by ``DocumentType``
to the EXCEL / PDF branch (stubs for now) or to a terminal ``unsupported`` node.
The builder is pure DI: it takes already-constructed activities, like the rest of
the codebase.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from doci.activities import FinalizeMedia
from doci.workflows.langgraph_document_mining.nodes import (
    excel_node,
    make_finalize_node,
    pdf_node,
    unsupported_node,
)
from doci.workflows.langgraph_document_mining.state import (
    DocumentMiningState,
    DocumentType,
)

_ROUTES = {
    DocumentType.EXCEL: "excel",
    DocumentType.PDF: "pdf",
    DocumentType.IMAGE: "image",
}


def route_by_type(state: DocumentMiningState) -> str:
    """Pick the branch for the classified ``document_type`` (else 'unsupported')."""
    return _ROUTES.get(state.get("document_type"), "unsupported")


def build_document_mining_graph(
    *,
    finalize: FinalizeMedia,
    image_graph: CompiledStateGraph,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build + compile the document-mining graph.

    ``image_graph`` is the compiled image child workflow, added directly as the
    ``image`` node so it shares this graph's ``checkpointer`` (it should be
    compiled without one of its own).
    """
    g = StateGraph(DocumentMiningState)
    g.add_node("finalize", make_finalize_node(finalize))
    g.add_node("excel", excel_node)
    g.add_node("pdf", pdf_node)
    g.add_node("image", image_graph)
    g.add_node("unsupported", unsupported_node)

    g.add_edge(START, "finalize")
    g.add_conditional_edges(
        "finalize",
        route_by_type,
        {
            "excel": "excel",
            "pdf": "pdf",
            "image": "image",
            "unsupported": "unsupported",
        },
    )
    g.add_edge("excel", END)
    g.add_edge("pdf", END)
    g.add_edge("image", END)
    g.add_edge("unsupported", END)
    return g.compile(checkpointer=checkpointer)
