"""Dossier-definition service over the ``dossier_def`` table.

CRUD with stable slug keys and soft delete (``deleted_at``). The documents a
dossier expects live in ``document_def`` (see :mod:`doci.userdata.documents`).
"""

from collections.abc import Sequence

from opentelemetry.trace import SpanKind
from psycopg import errors as pg_errors

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.common import ListPage, _page_bounds, gen_key
from doci.userdata.dossiers.models import DossierDef
from doci.userdata.errors import DuplicateKey, NotFound


_COLS = "id, key, name, description, deleted_at, created_at, updated_at"


@traced
class DossierDefService:
    """The dossier-definition domain over ``dossier_def``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_dossiers(
        self, *, limit: int | None = None, offset: int = 0
    ) -> ListPage:
        """List dossier definitions (newest first), paginated."""
        lim, off = _page_bounds(limit, offset)
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM dossier_def WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
            [lim + 1, off],
        )
        has_more = len(rows) > lim
        items = [DossierDef.from_row(r) for r in rows[:lim]]
        return ListPage(items=items, limit=lim, offset=off, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_dossier(self, key: str) -> DossierDef:
        """Fetch one dossier definition by key."""
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM dossier_def WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"dossier_def {key!r}")
        return DossierDef.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create_dossier(
        self, *, name: str, key: str | None = None, description: str | None = None
    ) -> DossierDef:
        """Create a dossier definition. ``key`` defaults to a slug of ``name``."""
        key = key or gen_key(name)
        try:
            row = await self._pg.fetch_one(
                f"INSERT INTO dossier_def (key, name, description) "
                f"VALUES (%s, %s, %s) RETURNING {_COLS}",
                [key, name, description],
            )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateKey(f"dossier_def {key!r}") from exc
        return DossierDef.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def update_dossier(
        self, key: str, *, name: str | None = None, description: str | None = None
    ) -> DossierDef:
        """Patch a dossier definition's name/description (None = leave unchanged)."""
        row = await self._pg.fetch_one(
            "UPDATE dossier_def SET "
            "name = COALESCE(%s, name), "
            "description = COALESCE(%s, description), "
            "updated_at = now() "
            f"WHERE key = %s AND deleted_at IS NULL RETURNING {_COLS}",
            [name, description, key],
        )
        if row is None:
            raise NotFound(f"dossier_def {key!r}")
        return DossierDef.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_dossiers(self, keys: Sequence[str]) -> int:
        """Soft-delete dossier definitions by key. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        rows = await self._pg.fetch_all(
            "UPDATE dossier_def SET deleted_at = now(), updated_at = now() "
            "WHERE key = ANY(%s) AND deleted_at IS NULL RETURNING id",
            [key_list],
        )
        return len(rows)
