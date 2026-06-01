"""Value objects for the media service (framework-agnostic)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import UUID


class MediaStatus(IntEnum):
    NEW = 0  # presigned URL issued; upload pending
    READY = 1  # uploaded + validated
    INVALID = 2  # validation failed


class MediaType(IntEnum):
    ORIGINAL = 0
    THUMB = 1
    PAGE = 2

    @property
    def key_prefix(self) -> str:
        """Object-key prefix for this type (e.g. ``original``)."""
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class MediaRecord:
    """A row of the ``media`` table."""

    id: UUID
    parent_id: UUID | None
    type: MediaType
    object_key: str
    name: str | None
    mime_type: str | None
    size_bytes: int | None
    status: MediaStatus
    deleted_at: datetime | None
    purge_after: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MediaRecord":
        return cls(
            id=row["id"],
            parent_id=row["parent_id"],
            type=MediaType(row["type"]),
            object_key=row["object_key"],
            name=row["name"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            status=MediaStatus(row["status"]),
            deleted_at=row["deleted_at"],
            purge_after=row["purge_after"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class UploadIntent:
    """Result of requesting an upload: the new media id + presigned PUT URL."""

    id: UUID
    upload_url: str


@dataclass(frozen=True, slots=True)
class MediaView:
    """A media record with its presigned view URL and (optionally) children."""

    media: MediaRecord
    view_url: str
    children: list["MediaView"] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MediaListPage:
    """A page of media records."""

    items: list[MediaRecord]
    limit: int
    offset: int
    has_more: bool
