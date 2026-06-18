"""Value object for a knowledge entry (framework-agnostic).

A :class:`Knowledge` entry is org-provided reference material an agent consults —
an authority matrix, a vendor policy, a glossary — expressed as natural-language
prose (``body``) rather than typed rows. ``description`` is a one-line summary for
discovery; ``body`` is the full markdown/plaintext content.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Knowledge:
    """A knowledge entry: a name, a short description, and a full-text body."""

    id: UUID
    key: str
    name: str
    description: str | None
    body: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Knowledge":
        return cls(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            body=row["body"],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
