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
    EnsureThumb,
    ExtractContentPdf,
    RenderImagePdf,
    SaveResultToPostgres,
    SplitPdf,
)
from doci.activities import annotate_text as _annotate_text
from doci.activities.reflect import annotate_reflect_enabled
from doci.documents import DocumentService
from doci.llm import build_chat_model
from doci.media import MediaService
from doci.results import WorkflowResultService
from doci.workflows.langgraph_document_mining_image.deps import build_image_graph
from doci.workflows.langgraph_document_mining_pdf.graph import (
    build_document_mining_pdf_graph,
)


def build_pdf_graph(
    media: MediaService,
    documents: DocumentService,
    results: WorkflowResultService,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Construct the activities + compile the PDF child graph.

    The embedded image graph inherits ``checkpointer`` so the per-page image
    runs (invoked imperatively under their own threads) are durable.
    """
    # Reflect model is built (and passed) only when the env switch allows it;
    # None ⇒ reflection can never run regardless of a run's per-run flag.
    reflect_model = (
        build_chat_model(
            _annotate_text.LLM_REFLECT_TASK,
            default_model=_annotate_text.LLM_REFLECT_DEFAULT_MODEL,
            default_max_tokens=_annotate_text.LLM_REFLECT_DEFAULT_MAX_TOKENS,
            default_params=_annotate_text.LLM_REFLECT_DEFAULT_PARAMS,
        )
        if annotate_reflect_enabled()
        else None
    )
    annotate_text = AnnotateText(
        build_chat_model(
            _annotate_text.LLM_TASK,
            default_model=_annotate_text.LLM_DEFAULT_MODEL,
            default_max_tokens=_annotate_text.LLM_DEFAULT_MAX_TOKENS,
            default_params=_annotate_text.LLM_DEFAULT_PARAMS,
        ),
        reflect_model=reflect_model,
    )
    image_graph = build_image_graph(media, results, checkpointer=checkpointer)
    return build_document_mining_pdf_graph(
        download=DownloadMedia(media),
        split=SplitPdf(),
        render_image_pdf=RenderImagePdf(),
        ensure_thumb=EnsureThumb(media),
        extract_pdf=ExtractContentPdf(),
        annotate_text=annotate_text,
        create_thumb_pdf=CreateThumbPdf(),
        save=SaveResultToPostgres(results),
        image_graph=image_graph,
        documents=documents,
        checkpointer=checkpointer,
    )
