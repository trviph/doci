"""Thumbnail node: download → create thumb → upload thumb (step 2.1).

Closure-DI over the activities, mirroring the parent's ``make_finalize_node``.
"""

from collections.abc import Awaitable, Callable

from doci.activities import CreateThumbImage, DownloadMedia, EnsureThumb
from doci.media.mime import MIME_PNG
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)

ImageNode = Callable[[DocumentMiningImageState], Awaitable[dict]]


def make_thumbnail_node(
    download: DownloadMedia, create_thumb: CreateThumbImage, ensure_thumb: EnsureThumb
) -> ImageNode:
    """Build the thumbnail node bound to its activities.

    Creates the thumbnail blob idempotently and returns its id; recording it
    against the document / region is the caller's job, keeping this graph reusable
    for a standalone image *and* a split PDF page."""

    async def thumbnail_node(state: DocumentMiningImageState) -> dict:
        media_id = state["media_id"]
        data = await download(media_id)

        async def render() -> tuple[bytes, str]:
            return await create_thumb(data), MIME_PNG

        rec = await ensure_thumb(media_id, render)
        return {"thumb_media_id": rec.id}

    return thumbnail_node
