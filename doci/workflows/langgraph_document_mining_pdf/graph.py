"""Compose the PDF document-mining child workflow as a LangGraph graph.

A simple linear chain — split into pages, process them all (bounded fan-out),
then join:

    START → split → process → done → END

Built with pure DI (already-constructed activities + the compiled image child
graph). Pass a ``checkpointer`` for standalone durable runs; leave it ``None``
when embedded as a parent subgraph (the parent's checkpointer applies).
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from doci.activities import (
    AnnotateText,
    CreateThumbPdf,
    DownloadMedia,
    ExtractContentPdf,
    RenderImagePdf,
    SaveResult,
    SplitPdf,
    UploadMedia,
)
from doci.workflows.langgraph_document_mining_pdf.nodes import (
    MAX_PAGE_CONCURRENCY,
    done_node,
    make_process_node,
    make_split_node,
)
from doci.workflows.langgraph_document_mining_pdf.state import DocumentMiningPdfState


def build_document_mining_pdf_graph(
    *,
    download: DownloadMedia,
    split: SplitPdf,
    render_image_pdf: RenderImagePdf,
    upload: UploadMedia,
    extract_pdf: ExtractContentPdf,
    annotate_text: AnnotateText,
    create_thumb_pdf: CreateThumbPdf,
    save: SaveResult,
    image_graph: CompiledStateGraph,
    max_concurrency: int = MAX_PAGE_CONCURRENCY,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build + compile the PDF document-mining child graph."""
    g = StateGraph(DocumentMiningPdfState)
    g.add_node("split", make_split_node(download, split, render_image_pdf, upload))
    g.add_node(
        "process",
        make_process_node(
            download,
            upload,
            extract_pdf,
            annotate_text,
            create_thumb_pdf,
            save,
            image_graph,
            max_concurrency=max_concurrency,
        ),
    )
    g.add_node("done", done_node)

    g.add_edge(START, "split")
    g.add_edge("split", "process")
    g.add_edge("process", "done")
    g.add_edge("done", END)
    return g.compile(checkpointer=checkpointer)