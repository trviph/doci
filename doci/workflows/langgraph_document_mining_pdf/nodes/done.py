"""Terminal node: the split → process chain ends here, then END."""

from doci.workflows.langgraph_document_mining_pdf.state import DocumentMiningPdfState


async def done_node(state: DocumentMiningPdfState) -> dict:
    """Terminal join; nothing to update."""
    return {}
