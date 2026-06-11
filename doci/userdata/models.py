"""Value objects for the user data layer (framework-agnostic).

Three concerns share this module:

- **document groups** — :class:`DocumentGroup` + :class:`DocumentGroupItem`: a
  dossier type and the documents it should contain. An item's ``fields`` are the
  shared :class:`FieldSpec` watchlist the annotate step extracts.
- **audit rules** — :class:`AuditRule`: a structured envelope plus a tagged-union
  ``check`` body (:class:`CheckPrompt` | :class:`CheckExpr`).
- **reference datasets** — :class:`ReferenceDataset` + :class:`ReferenceRecord`:
  the unified, schema-on-read registry (authority matrix, approved vendors, …),
  each row's ``data`` conforming to the dataset's ``field_schema``.

``key`` is optional everywhere a ``name`` exists; :func:`gen_key` derives a stable
slug from the name (lowercase, hyphen-joined, ≤5 segments, random 6-char suffix).
"""

import re
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from doci.activities.fields import FieldSpec

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

# region document groups ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentGroupItem:
    """One expected document within a group, with its fields-to-look-for."""

    id: UUID
    group_id: UUID
    key: str
    name: str
    description: str | None
    fields: list[FieldSpec]
    required: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DocumentGroupItem":
        return cls(
            id=row["id"],
            group_id=row["group_id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            fields=[FieldSpec.model_validate(f) for f in (row["fields"] or [])],
            required=row["required"],
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class DocumentGroup:
    """A dossier type. ``items`` is populated by :meth:`get_group`, else empty."""

    id: UUID
    key: str
    name: str
    description: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[DocumentGroupItem] = field(default_factory=list)

    @classmethod
    def from_row(
        cls, row: dict[str, Any], items: list[DocumentGroupItem] | None = None
    ) -> "DocumentGroup":
        return cls(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            items=items or [],
        )


# endregion

# region audit rules ----------------------------------------------------------


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    BLOCK = 2


class Selector(BaseModel):
    """An ``applies_to`` selector: a group key and/or a document (item) key."""

    group: str | None = None
    document: str | None = None


class CheckPrompt(BaseModel):
    """An LLM-judged check (the v1 live path)."""

    type: Literal["prompt"] = "prompt"
    prompt: str


class CheckExpr(BaseModel):
    """A deterministic expression check (stored now; evaluator deferred)."""

    type: Literal["expr"] = "expr"
    expr: str


Check = Annotated[CheckPrompt | CheckExpr, Field(discriminator="type")]
_CHECK_ADAPTER: TypeAdapter[CheckPrompt | CheckExpr] = TypeAdapter(Check)


def parse_check(value: dict[str, Any]) -> CheckPrompt | CheckExpr:
    """Validate a stored ``check_body`` dict into the tagged union."""
    return _CHECK_ADAPTER.validate_python(value)


@dataclass(frozen=True, slots=True)
class AuditRule:
    """An audit rule: structured envelope + a ``check`` union body."""

    id: UUID
    key: str
    name: str
    description: str | None
    applies_to: list[Selector]
    reference_keys: list[str]
    check: CheckPrompt | CheckExpr
    severity: Severity
    enabled: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AuditRule":
        return cls(
            id=row["id"],
            key=row["key"],
            name=row["name"],
            description=row["description"],
            applies_to=[Selector.model_validate(s) for s in (row["applies_to"] or [])],
            reference_keys=list(row["reference_keys"] or []),
            check=parse_check(row["check_body"]),
            severity=Severity(row["severity"]),
            enabled=row["enabled"],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


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
