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
    EnsureThumb,
    ExtractContentImage,
    SaveResultToPostgres,
)
from doci.activities import annotate_image as _annotate
from doci.activities import extract_content_image as _extract
from doci.activities.reflect import annotate_reflect_enabled
from doci.llm import build_chat_model
from doci.media import MediaService
from doci.results import WorkflowResultService
from doci.workflows.langgraph_document_mining_image.graph import (
    build_document_mining_image_graph,
)


def build_image_graph(
    media: MediaService,
    results: WorkflowResultService,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
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
    # Reflect model is built (and passed) only when the env switch allows it;
    # None ⇒ reflection can never run regardless of a run's per-run flag.
    reflect_model = (
        build_chat_model(
            _annotate.LLM_REFLECT_TASK,
            default_model=_annotate.LLM_REFLECT_DEFAULT_MODEL,
            default_max_tokens=_annotate.LLM_REFLECT_DEFAULT_MAX_TOKENS,
            default_params=_annotate.LLM_REFLECT_DEFAULT_PARAMS,
        )
        if annotate_reflect_enabled()
        else None
    )
    annotate = AnnotateImage(
        build_chat_model(
            _annotate.LLM_TASK,
            default_model=_annotate.LLM_DEFAULT_MODEL,
            default_max_tokens=_annotate.LLM_DEFAULT_MAX_TOKENS,
            default_params=_annotate.LLM_DEFAULT_PARAMS,
        ),
        reflect_model=reflect_model,
    )
    return build_document_mining_image_graph(
        download=DownloadMedia(media),
        create_thumb=CreateThumbImage(),
        ensure_thumb=EnsureThumb(media),
        extract=extract,
        annotate=annotate,
        save=SaveResultToPostgres(results),
        checkpointer=checkpointer,
    )
