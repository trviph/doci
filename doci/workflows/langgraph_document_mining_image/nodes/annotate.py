"""Annotate node: download → annotate the image → save (step 3).

Runs ``AnnotateImage`` on the image bytes (a vision pass), independent of the
extracted text. Sequenced after extract in the graph.
"""

from doci.activities import AnnotateImage, DownloadMedia, SaveResult
from doci.workflows.langgraph_document_mining_image.nodes.thumbnail import ImageNode
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


def make_annotate_node(
    download: DownloadMedia, annotate: AnnotateImage, save: SaveResult
) -> ImageNode:
    """Build the annotate node bound to its activities."""

    async def annotate_node(state: DocumentMiningImageState) -> dict:
        media_id = state["media_id"]
        data = await download(media_id)
        annotation = await annotate(data)
        ref = await save(
            state["execution_id"], media_id, "annotation.json",
            annotation.model_dump_json(),
        )
        return {"annotation_ref": ref}

    return annotate_node
