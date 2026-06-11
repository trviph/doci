"""Annotate node: download → annotate the image → save (step 3).

Runs ``AnnotateImage`` on the image bytes (a vision pass), independent of the
extracted text. Sequenced after extract in the graph.
"""

from doci.activities import AnnotateImage, DownloadMedia, SaveResult
from doci.activities.fields import GroupSpec
from doci.workflows.langgraph_document_mining_image.nodes.thumbnail import ImageNode
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


def make_annotate_node(
    download: DownloadMedia, annotate: AnnotateImage, save: SaveResult
) -> ImageNode:
    """Build the annotate node bound to its activities."""

    async def annotate_node(state: DocumentMiningImageState) -> dict:
        data = await download(state["media_id"])
        gs = state.get("group_spec")
        group = GroupSpec.model_validate(gs) if gs else None
        annotation = await annotate(data, group=group)
        ref = await save(
            state["execution_id"],
            state["part_id"],
            "annotation.json",
            annotation.model_dump_json(),
        )
        return {"annotation_ref": ref}

    return annotate_node
