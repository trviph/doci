"""Image-branch nodes: bracket the image child graph with its part lifecycle.

A standalone image isn't split, so its single "page" is the file as uploaded.
``prepare_image`` registers that source part (idempotent, keyed on the page-1
locator — the same part the standalone IMAGE task creates) and surfaces its
``part_id`` so the image child graph can attach results/thumbnail to it.
``record_image_thumb`` records the thumbnail the child produced back onto the
part. Both are closures over the injected ``DocumentService``, mirroring the
PDF nodes' constructor-injection style.
"""

from collections.abc import Awaitable, Callable

from doci.documents import DocumentService, PartKind
from doci.workflows.langgraph_document_mining.state import DocumentMiningState

ImagePartNode = Callable[[DocumentMiningState], Awaitable[dict]]


def make_prepare_image_node(documents: DocumentService) -> ImagePartNode:
    """Build the node that ensures the image's single source part before mining."""

    async def prepare_image_node(state: DocumentMiningState) -> dict:
        part = await documents.ensure_source_part(
            state["document_id"], kind=PartKind.IMAGE
        )
        return {"part_id": part.id}

    return prepare_image_node


def make_record_image_thumb_node(documents: DocumentService) -> ImagePartNode:
    """Build the node that records the image child's thumbnail onto the part."""

    async def record_image_thumb_node(state: DocumentMiningState) -> dict:
        thumb_media_id = state.get("thumb_media_id")
        if thumb_media_id is not None:
            await documents.set_part_thumb(state["part_id"], thumb_media_id)
        return {}

    return record_image_thumb_node
