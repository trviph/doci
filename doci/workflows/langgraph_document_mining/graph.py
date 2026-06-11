"""Compose the document-mining workflow as a LangGraph ``StateGraph``.

Entry node finalizes + classifies; a conditional edge routes by ``DocumentType``
to the PDF / IMAGE child graphs, or to a terminal ``unsupported`` node. The
builder is pure DI: it takes already-constructed activities + the compiled child
graphs, like the rest of the codebase.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from doci.activities import FinalizeDocument
from doci.documents import DocumentService
from doci.workflows.langgraph_document_mining.nodes import (
    make_finalize_node,
    make_prepare_image_node,
    make_record_image_thumb_node,
    unsupported_node,
)
from doci.workflows.langgraph_document_mining.state import (
    DocumentMiningState,
    DocumentType,
)

_ROUTES = {
    DocumentType.PDF: "pdf",
    DocumentType.IMAGE: "image",
}


def route_by_type(state: DocumentMiningState) -> str:
    """Pick the branch for the classified ``document_type`` (else 'unsupported')."""
    return _ROUTES.get(state.get("document_type"), "unsupported")


def build_document_mining_graph(
    *,
    finalize: FinalizeDocument,
    documents: DocumentService,
    image_graph: CompiledStateGraph,
    pdf_graph: CompiledStateGraph,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build + compile the document-mining graph.

    ``image_graph`` / ``pdf_graph`` are the compiled child workflows, added
    directly as the ``image`` / ``pdf`` nodes so they share this graph's
    ``checkpointer`` (they should be compiled without one of their own).

    A standalone image isn't split, so the image branch is bracketed by
    ``prepare_image`` (which registers the single source part and sets
    ``part_id`` the child needs) and ``record_image_thumb`` (which records the
    child's thumbnail onto that part) — the same lifecycle the PDF branch does
    per page and the standalone IMAGE task does inline.
    """
    g = StateGraph(DocumentMiningState)
    g.add_node("finalize", make_finalize_node(finalize))
    g.add_node("pdf", pdf_graph)
    g.add_node("prepare_image", make_prepare_image_node(documents))
    g.add_node("image", image_graph)
    g.add_node("record_image_thumb", make_record_image_thumb_node(documents))
    g.add_node("unsupported", unsupported_node)

    g.add_edge(START, "finalize")
    g.add_conditional_edges(
        "finalize",
        route_by_type,
        {
            "pdf": "pdf",
            "image": "prepare_image",
            "unsupported": "unsupported",
        },
    )
    g.add_edge("prepare_image", "image")
    g.add_edge("image", "record_image_thumb")
    g.add_edge("record_image_thumb", END)
    g.add_edge("pdf", END)
    g.add_edge("unsupported", END)
    return g.compile(checkpointer=checkpointer)
