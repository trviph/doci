"""Terminal node for the document-mining graph.

``unsupported_node`` records why a media wasn't processed and ends the run (the
PDF and IMAGE branches are compiled child graphs, added directly in ``graph.py``).
"""

from doci.workflows.langgraph_document_mining.state import DocumentMiningState


async def unsupported_node(state: DocumentMiningState) -> dict:
    """Record the unsupported MIME type and end gracefully (no exception)."""
    return {"unsupported_reason": f"unsupported type: {state.get('mime_type')}"}
