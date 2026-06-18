"""Value object for a document definition (framework-agnostic).

A :class:`DocumentDef` is one kind of document expected within a dossier (m‑1) —
e.g. a "VAT invoice" within a "payment request" dossier — carrying a name, an
optional description, and an optional plaintext ``look_for`` note describing what
to look for in such a document.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DocumentDef:
    """A document definition belonging to one dossier."""

    id: UUID
    dossier_id: UUID
    key: str
    name: str
    description: str | None
    look_for: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DocumentDef":
        return cls(
            id=row["id"],
            dossier_id=row["dossier_id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            look_for=row["look_for"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
