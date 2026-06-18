"""Value object for an agent rule (framework-agnostic).

An :class:`AgentRule` is a named, free-text markdown rule that an agent applies
to the dossiers it's linked to (via the ``agent_rule_dossier`` m‑n table). It is
deliberately generic — audit is one kind of rule, but others may run too — so it
carries only a name and a markdown ``body``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AgentRule:
    """An agent rule: a name + a markdown rule body."""

    id: UUID
    key: str
    name: str
    body: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AgentRule":
        return cls(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            body=row["body"],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
