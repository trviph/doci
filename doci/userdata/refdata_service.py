"""Reference-data service: the unified schema-on-read registry.

Owns ``reference_dataset`` + ``reference_record``. One pair of discover
(:meth:`list_datasets`) + query (:meth:`query`) methods serves *every* dataset
(authority matrix, approved vendors, …) — the surface a future MCP tool wraps.
Each dataset declares a ``field_schema``; records are validated against it on
write, and query filters are validated against it on read so callers get honest
errors instead of silent empty results.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from opentelemetry.trace import SpanKind
from psycopg2 import errors as pg_errors
from psycopg2.extras import Json, register_uuid

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.errors import DuplicateKey, NotFound, SchemaViolation, UnknownField
from doci.userdata.models import (
    DatasetInfo,
    FieldDef,
    FieldType,
    ListPage,
    ReferenceDataset,
    ReferenceRecord,
    gen_key,
)

register_uuid()

_DEFAULT_PAGE = 50
_MAX_PAGE = 500

_DATASET_COLS = (
    "id, key, name, description, field_schema, deleted_at, created_at, updated_at"
)
_RECORD_COLS = "id, dataset_id, key, data, created_at, updated_at"


def _type_ok(value: Any, ftype: FieldType) -> bool:
    if ftype is FieldType.STRING:
        return isinstance(value, str)
    if ftype is FieldType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype is FieldType.BOOL:
        return isinstance(value, bool)
    if ftype is FieldType.DATE:
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value[:10])
        except ValueError:
            return False
        return True
    return False


def _coerce(value: Any, ftype: FieldType) -> Any:
    """Coerce a (typically string) filter value to the schema's type so JSONB
    containment matches the stored value (e.g. ``"5000"`` → ``5000``)."""
    if ftype is FieldType.NUMBER:
        try:
            f = float(value)
        except TypeError, ValueError:
            return value
        return int(f) if f.is_integer() else f
    if ftype is FieldType.BOOL:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "y")
    return value


@traced
class ReferenceDataService:
    """The unified reference-dataset registry over ``reference_dataset`` + records."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    # region datasets (catalog + discovery)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_datasets(self) -> list[DatasetInfo]:
        """Discover all datasets with their schema + live record count."""
        rows = await self._pg.fetch_all(
            "SELECT d.key, d.name, d.description, d.field_schema, "
            "       COUNT(r.id) FILTER (WHERE r.deleted_at IS NULL) AS record_count "
            "FROM reference_dataset d "
            "LEFT JOIN reference_record r ON r.dataset_id = d.id "
            "WHERE d.deleted_at IS NULL "
            "GROUP BY d.id ORDER BY d.created_at DESC, d.id",
        )
        return [DatasetInfo.from_row(r) for r in rows]

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_dataset(self, key: str) -> ReferenceDataset:
        row = await self._dataset_row(key)
        return ReferenceDataset.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create_dataset(
        self,
        *,
        name: str,
        field_schema: Sequence[FieldDef],
        key: str | None = None,
        description: str | None = None,
    ) -> ReferenceDataset:
        """Register a dataset. ``key`` defaults to a slug derived from ``name``."""
        key = key or gen_key(name)
        schema_json = Json([f.model_dump(mode="json") for f in field_schema])
        try:
            row = await self._pg.fetch_one(
                "INSERT INTO reference_dataset (key, name, description, field_schema) "
                f"VALUES (%s, %s, %s, %s) RETURNING {_DATASET_COLS}",
                [key, name, description, schema_json],
            )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateKey(f"reference_dataset {key!r}") from exc
        return ReferenceDataset.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def update_dataset(
        self,
        key: str,
        *,
        name: str | None = None,
        description: str | None = None,
        field_schema: Sequence[FieldDef] | None = None,
    ) -> ReferenceDataset:
        """Patch a dataset; ``None`` arguments leave the column unchanged."""
        schema_json = (
            Json([f.model_dump(mode="json") for f in field_schema])
            if field_schema is not None
            else None
        )
        row = await self._pg.fetch_one(
            "UPDATE reference_dataset SET "
            "name = COALESCE(%s, name), "
            "description = COALESCE(%s, description), "
            "field_schema = COALESCE(%s, field_schema), "
            "updated_at = now() "
            f"WHERE key = %s AND deleted_at IS NULL RETURNING {_DATASET_COLS}",
            [name, description, schema_json, key],
        )
        if row is None:
            raise NotFound(f"reference_dataset {key!r}")
        return ReferenceDataset.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_datasets(self, keys: Sequence[str]) -> int:
        """Soft-delete datasets by key. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        rows = await self._pg.fetch_all(
            "UPDATE reference_dataset SET deleted_at = now(), updated_at = now() "
            "WHERE key = ANY(%s) AND deleted_at IS NULL RETURNING id",
            [key_list],
        )
        return len(rows)

    # endregion

    # region records (author + query)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def upsert_record(
        self, dataset_key: str, *, data: Mapping[str, Any], key: str | None = None
    ) -> ReferenceRecord:
        """Insert/update a record (validated against the dataset schema).

        A provided ``key`` upserts on ``(dataset, key)``; an omitted one always
        inserts (NULL keys are distinct in Postgres)."""
        dataset = await self._dataset_row(dataset_key)
        schema = [FieldDef.model_validate(f) for f in (dataset["field_schema"] or [])]
        _validate_data(data, schema)
        if key is None:
            row = await self._pg.fetch_one(
                "INSERT INTO reference_record (dataset_id, key, data) "
                f"VALUES (%s, %s, %s) RETURNING {_RECORD_COLS}",
                [dataset["id"], None, Json(dict(data))],
            )
        else:
            row = await self._pg.fetch_one(
                "INSERT INTO reference_record (dataset_id, key, data) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (dataset_id, key) DO UPDATE SET "
                "data = EXCLUDED.data, deleted_at = NULL, updated_at = now() "
                f"RETURNING {_RECORD_COLS}",
                [dataset["id"], key, Json(dict(data))],
            )
        return ReferenceRecord.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def bulk_upsert(
        self, dataset_key: str, records: Sequence[Mapping[str, Any]]
    ) -> int:
        """Upsert many ``{key?, data}`` records in one transaction. Returns count."""
        dataset = await self._dataset_row(dataset_key)
        schema = [FieldDef.model_validate(f) for f in (dataset["field_schema"] or [])]
        for rec in records:
            _validate_data(rec.get("data", {}), schema)
        n = 0
        async with self._pg.transaction() as tx:
            for rec in records:
                data = Json(dict(rec.get("data", {})))
                rec_key = rec.get("key")
                if rec_key is None:
                    await tx.execute(
                        "INSERT INTO reference_record (dataset_id, key, data) "
                        "VALUES (%s, %s, %s)",
                        [dataset["id"], None, data],
                    )
                else:
                    await tx.execute(
                        "INSERT INTO reference_record (dataset_id, key, data) "
                        "VALUES (%s, %s, %s) "
                        "ON CONFLICT (dataset_id, key) DO UPDATE SET "
                        "data = EXCLUDED.data, deleted_at = NULL, updated_at = now()",
                        [dataset["id"], rec_key, data],
                    )
                n += 1
        return n

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def query(
        self,
        dataset_key: str,
        *,
        filters: Mapping[str, Any] | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> ListPage:
        """Query a dataset's records: JSONB-containment equality filters (validated
        against the schema) + optional substring ``search``. Paginated."""
        dataset = await self._dataset_row(dataset_key)
        schema = [FieldDef.model_validate(f) for f in (dataset["field_schema"] or [])]
        by_name = {f.name: f for f in schema}

        where = ["dataset_id = %s", "deleted_at IS NULL"]
        params: list[Any] = [dataset["id"]]
        if filters:
            coerced: dict[str, Any] = {}
            for name, value in filters.items():
                fdef = by_name.get(name)
                if fdef is None:
                    raise UnknownField(
                        f"{name!r} not in dataset {dataset_key!r} schema"
                    )
                coerced[name] = _coerce(value, fdef.type)
            where.append("data @> %s::jsonb")
            params.append(Json(coerced))
        if search:
            where.append("data::text ILIKE %s")
            params.append(f"%{search}%")

        lim = max(1, min(limit or _DEFAULT_PAGE, _MAX_PAGE))
        off = max(0, offset)
        params.extend([lim + 1, off])
        rows = await self._pg.fetch_all(
            f"SELECT {_RECORD_COLS} FROM reference_record "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY key NULLS LAST, created_at LIMIT %s OFFSET %s",
            params,
        )
        has_more = len(rows) > lim
        items = [ReferenceRecord.from_row(r) for r in rows[:lim]]
        return ListPage(items=items, limit=lim, offset=off, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_record(self, dataset_key: str, key: str) -> ReferenceRecord:
        dataset = await self._dataset_row(dataset_key)
        row = await self._pg.fetch_one(
            f"SELECT {_RECORD_COLS} FROM reference_record "
            "WHERE dataset_id = %s AND key = %s AND deleted_at IS NULL",
            [dataset["id"], key],
        )
        if row is None:
            raise NotFound(f"record {key!r} in dataset {dataset_key!r}")
        return ReferenceRecord.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_records(self, dataset_key: str, keys: Sequence[str]) -> int:
        """Soft-delete records by natural key within a dataset. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        dataset = await self._dataset_row(dataset_key)
        rows = await self._pg.fetch_all(
            "UPDATE reference_record SET deleted_at = now(), updated_at = now() "
            "WHERE dataset_id = %s AND key = ANY(%s) AND deleted_at IS NULL "
            "RETURNING id",
            [dataset["id"], key_list],
        )
        return len(rows)

    # endregion

    # region private
    async def _dataset_row(self, key: str) -> dict[str, Any]:
        row = await self._pg.fetch_one(
            f"SELECT {_DATASET_COLS} FROM reference_dataset "
            "WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"reference_dataset {key!r}")
        return row

    # endregion


def _validate_data(data: Mapping[str, Any], schema: Sequence[FieldDef]) -> None:
    """Check a record's ``data`` against the dataset schema: required fields are
    present and declared fields that are set have the right type. Extra keys are
    allowed (schema-on-read)."""
    by_name = {f.name: f for f in schema}
    for f in schema:
        if f.required and data.get(f.name) is None:
            raise SchemaViolation(f"missing required field {f.name!r}")
    for name, value in data.items():
        fdef = by_name.get(name)
        if fdef is None or value is None:
            continue
        if not _type_ok(value, fdef.type):
            raise SchemaViolation(f"field {name!r} expected {fdef.type.value}")
