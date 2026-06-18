"""Value objects for the reference-data registry (framework-agnostic).

:class:`ReferenceDataset` + :class:`ReferenceRecord` are the unified,
schema-on-read registry (authority matrix, approved vendors, …), each row's
``data`` conforming to the dataset's ``field_schema``.

``key`` is optional everywhere a ``name`` exists; :func:`gen_key` derives a stable
slug from the name (lowercase, hyphen-joined, ≤5 segments, random 6-char suffix).

(Dossier/document/agent-rule definitions live in the per-concern ``dossiers`` /
``documents`` / ``rules`` submodules.)
"""

import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

# region key derivation -------------------------------------------------------

_KEY_ALPHABET = string.ascii_lowercase + string.digits
_KEY_MAX_SEGMENTS = 5
_KEY_SUFFIX_LEN = 6


def gen_key(name: str) -> str:
    """Derive a slug key from a display name.

    Lowercase, alphanumeric runs hyphen-joined, capped at 5 segments, with a
    random 6-char suffix so two same-named entities don't collide:

    - ``"THE ORIGINAL PAYMENT"``                 → ``"the-original-payment-xqs2y6"``
    - ``"THIS IS SO FIRE! I LOVE IT SO MUCH <3"`` → ``"this-is-so-fire-i-zsw213"``
    """
    words = re.findall(r"[a-z0-9]+", name.lower())[:_KEY_MAX_SEGMENTS]
    suffix = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_SUFFIX_LEN))
    stem = "-".join(words)
    return f"{stem}-{suffix}" if stem else suffix


# endregion

# region shared pagination ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ListPage:
    """A page of records (newest first). ``items`` is typed by the caller."""

    items: list[Any]
    limit: int
    offset: int
    has_more: bool


# endregion

# region reference datasets (unified registry) --------------------------------


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOL = "bool"
    DATE = "date"


class FieldDef(BaseModel):
    """One declared column of a reference dataset's ``field_schema``."""

    name: str
    type: FieldType = FieldType.STRING
    description: str | None = None
    required: bool = False


@dataclass(frozen=True, slots=True)
class ReferenceDataset:
    """A unified reference dataset (the catalog row)."""

    id: UUID
    key: str
    name: str
    description: str | None
    field_schema: list[FieldDef]
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReferenceDataset":
        return cls(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            field_schema=[
                FieldDef.model_validate(f) for f in (row["field_schema"] or [])
            ],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """Discovery view of a dataset: its schema + how many records it holds."""

    key: str
    name: str
    description: str | None
    field_schema: list[FieldDef]
    record_count: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DatasetInfo":
        return cls(
            key=row["key"],
            name=row["name"],
            description=row["description"],
            field_schema=[
                FieldDef.model_validate(f) for f in (row["field_schema"] or [])
            ],
            record_count=row["record_count"],
        )


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    """One row within a dataset; ``data`` conforms to the dataset's schema."""

    id: UUID
    dataset_id: UUID
    key: str | None
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReferenceRecord":
        return cls(
            id=row["id"],
            dataset_id=row["dataset_id"],
            key=row["key"],
            data=row["data"] or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# endregion
