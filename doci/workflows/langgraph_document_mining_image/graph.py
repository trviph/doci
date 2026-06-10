"""Compose the image document-mining child workflow as a LangGraph graph.

Two branches run in parallel from START — thumbnail, and extract→annotate — and
join at ``done``:

    START → thumbnail ───────────────┐
    START → extract → annotate ──────┴→ done → END

Built with pure DI (already-constructed activities). Pass a ``checkpointer`` for
standalone durable runs; leave it ``None`` when embedded as a parent subgraph (the
parent's checkpointer applies).
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from doci.activities import (
    AnnotateImage,
    CreateThumbImage,
    DownloadMedia,
    EnsureThumb,
    ExtractContentImage,
    SaveResult,
)
from doci.workflows.langgraph_document_mining_image.nodes import (
    done_node,
    make_annotate_node,
    make_extract_node,
    make_thumbnail_node,
)
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


def build_document_mining_image_graph(
    *,
    download: DownloadMedia,
    create_thumb: CreateThumbImage,
    ensure_thumb: EnsureThumb,
    extract: ExtractContentImage,
    annotate: AnnotateImage,
    save: SaveResult,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build + compile the image document-mining child graph."""
    g = StateGraph(DocumentMiningImageState)
    g.add_node("thumbnail", make_thumbnail_node(download, create_thumb, ensure_thumb))
    g.add_node("extract", make_extract_node(download, extract, save))
    g.add_node("annotate", make_annotate_node(download, annotate, save))
    g.add_node("done", done_node)

    g.add_edge(START, "thumbnail")
    g.add_edge(START, "extract")
    g.add_edge("extract", "annotate")
    g.add_edge("thumbnail", "done")
    g.add_edge("annotate", "done")
    g.add_edge("done", END)
    return g.compile(checkpointer=checkpointer)
