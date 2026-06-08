"""Build the PDF child graph from shared clients.

Shared by the standalone child task (durable, with a checkpointer) and the parent
task (which embeds the child as a subgraph). The checkpointer is threaded down to
the embedded image child graph so per-page image runs are durable too.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from doci.activities import (
    AnnotateText,
    CreateThumbPdf,
    DownloadMedia,
    ExtractContentPdf,
    RenderImagePdf,
    SaveResultToDisk,
    SplitPdf,
    UploadMedia,
)
from doci.activities.annotate_text import LLM_DEFAULT_MODEL as _ANNOTATE_MODEL
from doci.activities.annotate_text import LLM_TASK as _ANNOTATE_TASK
from doci.llm import build_chat_model
from doci.media import MediaService
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.langgraph_document_mining_pdf.graph import (
    build_document_mining_pdf_graph,
)


def build_pdf_graph(
    media: MediaService, *, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Construct the activities + compile the PDF child graph.

    The embedded image graph inherits ``checkpointer`` so the per-page image
    runs (invoked imperatively under their own threads) are durable.
    """
    annotate_text = AnnotateText(
        build_chat_model(_ANNOTATE_TASK, default_model=_ANNOTATE_MODEL)
    )
    image_graph = build_image_graph(media, checkpointer=checkpointer)
    return build_document_mining_pdf_graph(
        download=DownloadMedia(media),
        split=SplitPdf(),
        render_image_pdf=RenderImagePdf(),
        upload=UploadMedia(media),
        extract_pdf=ExtractContentPdf(),
        annotate_text=annotate_text,
        create_thumb_pdf=CreateThumbPdf(),
        save=SaveResultToDisk(),
        image_graph=image_graph,
        checkpointer=checkpointer,
    )