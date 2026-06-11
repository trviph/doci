"""Value objects for the media service (framework-agnostic).

``media`` is pure blob storage: an object in the store plus its content metadata
and soft-delete/purge bookkeeping. The document domain (originals, pages,
regions, lifecycle status) lives in :mod:`doci.documents`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MediaRecord:
    """A row of the ``media`` table — one stored blob."""

    id: UUID
    object_key: str
    mime_type: str | None
    size_bytes: int | None
    deleted_at: datetime | None
    purge_after: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MediaRecord":
        return cls(
            id=row["id"],
            object_key=row["object_key"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            deleted_at=row["deleted_at"],
            purge_after=row["purge_after"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class MediaView:
    """A media record with its presigned view URL and (optionally) children."""

    media: MediaRecord
    view_url: str
    children: list["MediaView"] = field(default_factory=list)
