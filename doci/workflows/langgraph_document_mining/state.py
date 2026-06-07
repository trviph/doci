"""Graph state + supported-type classification for the document-mining workflow.

The workflow's first node finalizes an uploaded media and classifies it into a
``DocumentType`` — the set of types this pipeline knows how to process. Anything
else is routed to a terminal ``unsupported`` node (see ``graph.py``).
"""

from enum import Enum
from typing import TypedDict
from uuid import UUID

from doci.media.mime import MIME_PDF, MIME_XLSX


class DocumentType(str, Enum):
    """A media type this workflow can process."""

    EXCEL = "excel"
    PDF = "pdf"


# MIME type -> supported DocumentType. Constants come from doci.media.mime so the
# accepted set stays in sync with upload validation.
_BY_MIME: dict[str, DocumentType] = {
    MIME_PDF: DocumentType.PDF,
    MIME_XLSX: DocumentType.EXCEL,
}


def classify(mime: str | None) -> DocumentType | None:
    """Map a finalized media's MIME type to a ``DocumentType`` (None if unsupported)."""
    if mime is None:
        return None
    return _BY_MIME.get(mime)


class DocumentMiningState(TypedDict, total=False):
    """State threaded through the document-mining graph."""

    media_id: UUID  # input
    mime_type: str | None  # set by the finalize node
    document_type: DocumentType | None  # set by the finalize node
    unsupported_reason: str | None  # set by the terminal unsupported node
