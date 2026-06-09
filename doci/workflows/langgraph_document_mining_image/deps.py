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
    SaveResultToDisk,
    UploadMedia,
)
from doci.activities import annotate_image as _annotate
from doci.activities import extract_content_image as _extract
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
            _extract.LLM_TASK,
            default_model=_extract.LLM_DEFAULT_MODEL,
            default_max_tokens=_extract.LLM_DEFAULT_MAX_TOKENS,
            default_params=_extract.LLM_DEFAULT_PARAMS,
        )
    )
    annotate = AnnotateImage(
        build_chat_model(
            _annotate.LLM_TASK,
            default_model=_annotate.LLM_DEFAULT_MODEL,
            default_max_tokens=_annotate.LLM_DEFAULT_MAX_TOKENS,
            default_params=_annotate.LLM_DEFAULT_PARAMS,
        )
    )
    return build_document_mining_image_graph(
        download=DownloadMedia(media),
        create_thumb=CreateThumbImage(),
        upload=UploadMedia(media),
        extract=extract,
        annotate=annotate,
        save=SaveResultToDisk(),
        checkpointer=checkpointer,
    )
