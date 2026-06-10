"""Value objects for the documents service (framework-agnostic).

A ``document`` is an uploaded file as a domain entity; a ``document_part`` is a
derived region of it (a page today, an arbitrary range later). Both reference
``media`` rows for their actual bytes. The ``locator`` on a part is the
idempotency key within its document.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

#: Zero-pad width for page locators, so object keys / locators sort in page
#: order lexically (``p0001`` < ``p0002`` < ``p0010``). Five digits → 99999 pages.
_PAGE_PAD = 5


def page_locator(page_number: int) -> str:
    """The locator for a 1-based page number (``1`` → ``p00001``)."""
    return f"p{page_number:0{_PAGE_PAD}d}"


class DocumentStatus(IntEnum):
    NEW = 0  # presigned URL issued; upload pending
    READY = 1  # uploaded + validated
    INVALID = 2  # validation failed


class PartKind(IntEnum):
    TEXT = 0  # extract via the text-layer path
    IMAGE = 1  # extract via the vision path


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """A row of the ``document`` table.

    ``object_key`` / ``mime_type`` / ``size_bytes`` are convenience fields joined
    from the original ``media`` row by the read queries; they are ``None`` when a
    row is built without the join.
    """

    id: UUID
    media_id: UUID
    thumb_media_id: UUID | None
    name: str | None
    status: DocumentStatus
    page_count: int | None
    deleted_at: datetime | None
    purge_after: datetime | None
    created_at: datetime
    updated_at: datetime
    object_key: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DocumentRecord":
        return cls(
            id=row["id"],
            media_id=row["media_id"],
            thumb_media_id=row["thumb_media_id"],
            name=row["name"],
            status=DocumentStatus(row["status"]),
            page_count=row["page_count"],
            deleted_at=row["deleted_at"],
            purge_after=row["purge_after"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            object_key=row.get("object_key"),
            mime_type=row.get("mime_type"),
            size_bytes=row.get("size_bytes"),
        )


@dataclass(frozen=True, slots=True)
class DocumentPartRecord:
    """A row of the ``document_part`` table — one derived region of a document."""

    id: UUID
    document_id: UUID
    locator: str
    kind: PartKind
    page_number: int | None
    media_id: UUID | None
    thumb_media_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DocumentPartRecord":
        return cls(
            id=row["id"],
            document_id=row["document_id"],
            locator=row["locator"],
            kind=PartKind(row["kind"]),
            page_number=row["page_number"],
            media_id=row["media_id"],
            thumb_media_id=row["thumb_media_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class UploadIntent:
    """Result of requesting an upload: the new document id + presigned PUT URL."""

    id: UUID
    upload_url: str


@dataclass(frozen=True, slots=True)
class DocumentListPage:
    """A page of document records."""

    items: list[DocumentRecord]
    limit: int
    offset: int
    has_more: bool
