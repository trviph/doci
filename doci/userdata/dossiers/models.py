"""Value object for a dossier definition (framework-agnostic).

A :class:`Dossier` is a named kind of case file — e.g. "payment request",
"marketing", "outsourcing software" — carrying only a name and a free-text
description. The documents it expects live in the ``document_def`` table (m‑1),
and the agent rules that run against it via the ``agent_rule_dossier`` link (m‑n).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Dossier:
    """A dossier definition: a name + a plaintext description."""

    id: UUID
    key: str
    name: str
    description: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Dossier":
        return cls(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
