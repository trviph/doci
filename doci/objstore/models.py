"""Framework-agnostic value objects returned by :class:`ObjStore`."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """Metadata for a stored object (from ``head_object``)."""

    bucket: str
    key: str
    size: int
    content_type: str | None
    etag: str | None
    last_modified: datetime | None
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class PresignedPost:
    """A presigned POST target: the form ``url`` and the fields to submit with it."""

    url: str
    fields: dict[str, str]
