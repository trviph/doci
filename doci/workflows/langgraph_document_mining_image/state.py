"""Graph state for the image document-mining child workflow.

Threaded through the graph as it thumbnails, transcribes, and annotates a single
image media. Only small references live in state — never the image bytes — so
checkpoints stay tiny; each node downloads the bytes it needs.
"""

from typing import TypedDict
from uuid import UUID


class DocumentMiningImageState(TypedDict, total=False):
    """State for the image-mining child graph."""

    media_id: UUID  # input (shared with the parent graph)
    thumb_media_id: UUID | None  # set by the thumbnail node
    extract_ref: str | None  # disk path of the extracted Markdown (FIXME: db)
    annotation_ref: str | None  # disk path of the annotation JSON (FIXME: db)
