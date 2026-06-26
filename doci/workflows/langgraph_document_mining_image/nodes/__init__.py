"""Image document-mining child-graph nodes."""

from doci.workflows.langgraph_document_mining_image.nodes.done import done_node
from doci.workflows.langgraph_document_mining_image.nodes.thumbnail import (
    ImageNode,
    make_thumbnail_node,
)
from doci.workflows.langgraph_document_mining_image.nodes.transcribe import (
    make_transcribe_node,
)

__all__ = [
    "ImageNode",
    "make_thumbnail_node",
    "make_transcribe_node",
    "done_node",
]
