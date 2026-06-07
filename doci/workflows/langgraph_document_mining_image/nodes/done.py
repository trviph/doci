"""Terminal join node (step 4): both branches converge here, then END."""

from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


async def done_node(state: DocumentMiningImageState) -> dict:
    """Join the thumbnail and extract→annotate branches; nothing to update."""
    return {}
