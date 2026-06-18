"""Value objects for the workflow-result store (framework-agnostic).

A ``workflow_result`` row is one stored artifact of a workflow run — the
extracted Markdown of a page, or the structured annotation of a document —
keyed by ``(execution_id, part_id, kind)``. The payload lives in a single JSONB
``content`` column so the (future) deepagents query tool reads every kind the
same way; see :class:`ResultKind` for how each kind shapes that column.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ResultKind(StrEnum):
    """The kinds of result a workflow persists.

    Each member's *value* is the artifact's extension-style name, so the enum
    stays string-compatible with the ``SaveResult`` interface and the literal
    call sites that already pass ``"extract.md"`` / ``"annotation.json"``.
    """

    EXTRACT = "extract.md"  # markdown / OCR text
    ANNOTATION = "annotation.json"  # TextAnnotation / ImageAnnotation

    @property
    def is_json(self) -> bool:
        """Whether the payload is itself JSON (stored as-is) vs plain text.

        Derived from the value's suffix, so a new ``*.json`` kind classifies
        itself without extra wiring.
        """
        return self.value.endswith(".json")


@dataclass(frozen=True, slots=True)
class WorkflowResultRecord:
    """A row of the ``workflow_result`` table.

    ``content`` is the parsed JSONB payload: the annotation object for
    ``ANNOTATION``, or ``{"result": <text>}`` for text kinds like ``EXTRACT``.
    """

    id: UUID
    execution_id: UUID
    part_id: UUID
    kind: ResultKind
    content: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "WorkflowResultRecord":
        return cls(
            id=row["id"],
            execution_id=row["execution_id"],
            part_id=row["part_id"],
            kind=ResultKind(row["kind"]),
            content=row["content"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class PageRef:
    """A page in a run's index: its part + classification (no full content).

    The compact view an audit agent scans first; ``item_key`` is the dossier
    document type the page was classified as (``None`` if unmatched/no dossier).
    """

    part_id: UUID
    page_number: int | None
    locator: str
    item_key: str | None
    category: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "PageRef":
        return cls(
            part_id=row["part_id"],
            page_number=row["page_number"],
            locator=row["locator"],
            item_key=row["item_key"],
            category=row["category"],
        )
