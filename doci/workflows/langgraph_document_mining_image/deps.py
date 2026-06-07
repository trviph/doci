"""Build the image child graph from shared clients.

Shared by the standalone child task (durable, with a checkpointer) and the parent
task (which embeds the child as a subgraph, so passes no checkpointer of its own).
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from doci.activities import (
    AnnotateImage,
    CreateThumbImage,
    DownloadMedia,
    ExtractContentImage,
    UploadMedia,
)
from doci.llm import build_chat_model
from doci.media import MediaService
from doci.workflows.langgraph_document_mining_image.graph import (
    build_document_mining_image_graph,
)


def build_image_graph(
    media: MediaService, *, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Construct the activities + compile the image child graph."""
    extract = ExtractContentImage(
        build_chat_model(
            ExtractContentImage.LLM_TASK,
            default_model=ExtractContentImage.LLM_DEFAULT_MODEL,
        )
    )
    annotate = AnnotateImage(
        build_chat_model(
            AnnotateImage.LLM_TASK, default_model=AnnotateImage.LLM_DEFAULT_MODEL
        )
    )
    return build_document_mining_image_graph(
        download=DownloadMedia(media),
        create_thumb=CreateThumbImage(),
        upload=UploadMedia(media),
        extract=extract,
        annotate=annotate,
        checkpointer=checkpointer,
    )
