"""Thumbnail node: download → create thumb → upload thumb (step 2.1).

Closure-DI over the activities, mirroring the parent's ``make_finalize_node``.
"""

from collections.abc import Awaitable, Callable

from doci.activities import CreateThumbImage, DownloadMedia, UploadMedia
from doci.media import MediaType
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)

ImageNode = Callable[[DocumentMiningImageState], Awaitable[dict]]


def make_thumbnail_node(
    download: DownloadMedia, create_thumb: CreateThumbImage, upload: UploadMedia
) -> ImageNode:
    """Build the thumbnail node bound to its activities."""

    async def thumbnail_node(state: DocumentMiningImageState) -> dict:
        media_id = state["media_id"]
        data = await download(media_id)
        thumb = await create_thumb(data)
        rec = await upload(thumb, parent_id=media_id, type=MediaType.THUMB)
        return {"thumb_media_id": rec.id}

    return thumbnail_node
