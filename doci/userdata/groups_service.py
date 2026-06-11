"""Document-group service: dossier definitions + their expected documents.

Owns ``document_group`` and ``document_group_item``. The mining pipeline consumes
:meth:`get_group` (the whole group, with each item's ``fields``) to drive the
group-aware annotate step; authoring is the REST surface.
"""

from collections.abc import Sequence
from uuid import UUID

from opentelemetry.trace import SpanKind
from psycopg2 import errors as pg_errors
from psycopg2.extras import Json, register_uuid

from doci.activities.fields import FieldSpec
from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.models import (
    DocumentGroup,
    DocumentGroupItem,
    ListPage,
    gen_key,
)

register_uuid()

_DEFAULT_PAGE = 50
_MAX_PAGE = 200

_GROUP_COLS = "id, key, name, description, deleted_at, created_at, updated_at"
_ITEM_COLS = (
    "id, group_id, key, name, description, fields, required, sort_order, "
    "created_at, updated_at"
)


def _page_bounds(limit: int | None, offset: int) -> tuple[int, int]:
    return max(1, min(limit or _DEFAULT_PAGE, _MAX_PAGE)), max(0, offset)


@traced
class DocumentGroupService:
    """The document-group domain over ``document_group`` + ``document_group_item``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_groups(
        self, *, limit: int | None = None, offset: int = 0
    ) -> ListPage:
        """List groups (newest first), paginated. Items are not loaded here."""
        lim, off = _page_bounds(limit, offset)
        rows = await self._pg.fetch_all(
            f"SELECT {_GROUP_COLS} FROM document_group WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
            [lim + 1, off],
        )
        has_more = len(rows) > lim
        items = [DocumentGroup.from_row(r) for r in rows[:lim]]
        return ListPage(items=items, limit=lim, offset=off, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_group(self, key: str) -> DocumentGroup:
        """Fetch one group with all its items (the shape mining consumes)."""
        row = await self._pg.fetch_one(
            f"SELECT {_GROUP_COLS} FROM document_group "
            "WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"document_group {key!r}")
        items = await self._items_for(row["id"])
        return DocumentGroup.from_row(row, items)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create_group(
        self, *, name: str, key: str | None = None, description: str | None = None
    ) -> DocumentGroup:
        """Create a group. ``key`` defaults to a slug derived from ``name``."""
        key = key or gen_key(name)
        try:
            row = await self._pg.fetch_one(
                f"INSERT INTO document_group (key, name, description) "
                f"VALUES (%s, %s, %s) RETURNING {_GROUP_COLS}",
                [key, name, description],
            )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateKey(f"document_group {key!r}") from exc
        return DocumentGroup.from_row(row, [])

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def update_group(
        self, key: str, *, name: str | None = None, description: str | None = None
    ) -> DocumentGroup:
        """Patch a group's name/description (None = leave unchanged)."""
        row = await self._pg.fetch_one(
            f"UPDATE document_group SET "
            "name = COALESCE(%s, name), "
            "description = COALESCE(%s, description), "
            "updated_at = now() "
            f"WHERE key = %s AND deleted_at IS NULL RETURNING {_GROUP_COLS}",
            [name, description, key],
        )
        if row is None:
            raise NotFound(f"document_group {key!r}")
        items = await self._items_for(row["id"])
        return DocumentGroup.from_row(row, items)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_groups(self, keys: Sequence[str]) -> int:
        """Soft-delete groups by key; their items cascade. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        rows = await self._pg.fetch_all(
            "UPDATE document_group SET deleted_at = now(), updated_at = now() "
            "WHERE key = ANY(%s) AND deleted_at IS NULL RETURNING id",
            [key_list],
        )
        return len(rows)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_items(self, group_key: str) -> list[DocumentGroupItem]:
        """List one group's items (ordered by ``sort_order``)."""
        group = await self._fetch_group_row(group_key)
        return await self._items_for(group["id"])

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def upsert_item(
        self,
        group_key: str,
        *,
        name: str,
        key: str | None = None,
        description: str | None = None,
        fields: Sequence[FieldSpec] | None = None,
        required: bool = True,
        sort_order: int = 0,
    ) -> DocumentGroupItem:
        """Create or update an item. Idempotent on ``(group, key)``; a provided
        ``key`` updates the existing item, an omitted one derives a fresh slug."""
        group = await self._fetch_group_row(group_key)
        key = key or gen_key(name)
        payload = Json([f.model_dump() for f in (fields or [])])
        row = await self._pg.fetch_one(
            f"INSERT INTO document_group_item "
            "(group_id, key, name, description, fields, required, sort_order) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (group_id, key) DO UPDATE SET "
            "name = EXCLUDED.name, description = EXCLUDED.description, "
            "fields = EXCLUDED.fields, required = EXCLUDED.required, "
            "sort_order = EXCLUDED.sort_order, updated_at = now() "
            f"RETURNING {_ITEM_COLS}",
            [group["id"], key, name, description, payload, required, sort_order],
        )
        return DocumentGroupItem.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_item(self, group_key: str, item_key: str) -> int:
        """Hard-delete one item (it carries no blobs). Returns rows removed."""
        group = await self._fetch_group_row(group_key)
        return await self._pg.execute(
            "DELETE FROM document_group_item WHERE group_id = %s AND key = %s",
            [group["id"], item_key],
        )

    # region private
    async def _fetch_group_row(self, key: str) -> dict:
        row = await self._pg.fetch_one(
            "SELECT id FROM document_group WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"document_group {key!r}")
        return row

    async def _items_for(self, group_id: UUID) -> list[DocumentGroupItem]:
        rows = await self._pg.fetch_all(
            f"SELECT {_ITEM_COLS} FROM document_group_item WHERE group_id = %s "
            "ORDER BY sort_order, key",
            [group_id],
        )
        return [DocumentGroupItem.from_row(r) for r in rows]

    # endregion
