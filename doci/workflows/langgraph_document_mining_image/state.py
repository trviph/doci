"""Graph state for the image document-mining child workflow.

Threaded through the graph as it thumbnails, transcribes, and annotates a single
image media. Only small references live in state — never the image bytes — so
checkpoints stay tiny; each node downloads the bytes it needs.
"""

from typing import TypedDict
from uuid import UUID


class DocumentMiningImageState(TypedDict, total=False):
    """State for the image-mining child graph."""

    media_id: UUID  # input: the blob to mine (original image, or a split PDF page)
    part_id: UUID  # input: the document_part this run produces results/thumb for
    document_id: UUID  # input: the owning document (threaded for parity; unused here)
    execution_id: UUID  # input (the workflow_execution row; used when saving results)
    dossier_spec: dict | None  # input: DossierSpec (dict) for dossier-aware annotate
    thumb_media_id: UUID | None  # set by the thumbnail node
    extract_ref: str | None  # disk path of the extracted Markdown (FIXME: db)
    annotation_ref: str | None  # disk path of the annotation JSON (FIXME: db)
