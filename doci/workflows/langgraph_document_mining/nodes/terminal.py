"""Terminal + placeholder nodes for the document-mining graph.

``unsupported_node`` records why a media wasn't processed and ends the run.
``excel_node`` / ``pdf_node`` are stubs the per-type pipelines will replace.
"""

from doci.workflows.langgraph_document_mining.state import DocumentMiningState


async def unsupported_node(state: DocumentMiningState) -> dict:
    """Record the unsupported MIME type and end gracefully (no exception)."""
    return {"unsupported_reason": f"unsupported type: {state.get('mime_type')}"}


async def excel_node(state: DocumentMiningState) -> dict:
    """EXCEL branch (stub)."""
    # TODO: extract → annotate (ExtractContentExcel → AnnotateText).
    return {}


async def pdf_node(state: DocumentMiningState) -> dict:
    """PDF branch (stub)."""
    # TODO: split → per-page extract/annotate (SplitPdf → ExtractContentPdf / AnnotateImage).
    return {}
