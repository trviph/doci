"""Knowledge service: natural-language reference entries over ``knowledge``.

CRUD with stable slug keys and soft delete (``deleted_at``). :meth:`list_knowledge`
takes an optional ``search`` — a substring ``ILIKE`` over name/description/body —
the surface a future agent/MCP tool reads the org's reference material through.
"""

from collections.abc import Sequence

from opentelemetry.trace import SpanKind
from psycopg2 import errors as pg_errors
from psycopg2.extras import register_uuid

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.common import ListPage, _page_bounds, gen_key
from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.knowledge.models import Knowledge

register_uuid()

_COLS = "id, key, name, description, body, deleted_at, created_at, updated_at"


def _like_term(search: str) -> str:
    """Escape LIKE metacharacters so a search term matches literally."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@traced
class KnowledgeService:
    """The knowledge domain over ``knowledge``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_knowledge(
        self, *, search: str | None = None, limit: int | None = None, offset: int = 0
    ) -> ListPage:
        """List entries (newest first), paginated. ``search`` is an optional
        substring match over name/description/body."""
        lim, off = _page_bounds(limit, offset)
        where = ["deleted_at IS NULL"]
        params: list = []
        if search:
            where.append(
                "(name ILIKE %s ESCAPE '\\' OR description ILIKE %s ESCAPE '\\' "
                "OR body ILIKE %s ESCAPE '\\')"
            )
            term = _like_term(search)
            params.extend([term, term, term])
        params.extend([lim + 1, off])
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM knowledge WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
            params,
        )
        has_more = len(rows) > lim
        items = [Knowledge.from_row(r) for r in rows[:lim]]
        return ListPage(items=items, limit=lim, offset=off, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_knowledge(self, key: str) -> Knowledge:
        """Fetch one entry by key."""
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM knowledge WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"knowledge {key!r}")
        return Knowledge.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create_knowledge(
        self,
        *,
        name: str,
        body: str,
        key: str | None = None,
        description: str | None = None,
    ) -> Knowledge:
        """Create an entry. ``key`` defaults to a slug derived from ``name``."""
        key = key or gen_key(name)
        try:
            row = await self._pg.fetch_one(
                f"INSERT INTO knowledge (key, name, description, body) "
                f"VALUES (%s, %s, %s, %s) RETURNING {_COLS}",
                [key, name, description, body],
            )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateKey(f"knowledge {key!r}") from exc
        return Knowledge.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def update_knowledge(
        self,
        key: str,
        *,
        name: str | None = None,
        description: str | None = None,
        body: str | None = None,
    ) -> Knowledge:
        """Patch an entry's name/description/body (None = leave unchanged)."""
        row = await self._pg.fetch_one(
            "UPDATE knowledge SET "
            "name = COALESCE(%s, name), "
            "description = COALESCE(%s, description), "
            "body = COALESCE(%s, body), "
            "updated_at = now() "
            f"WHERE key = %s AND deleted_at IS NULL RETURNING {_COLS}",
            [name, description, body, key],
        )
        if row is None:
            raise NotFound(f"knowledge {key!r}")
        return Knowledge.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_knowledge(self, keys: Sequence[str]) -> int:
        """Soft-delete entries by key. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        rows = await self._pg.fetch_all(
            "UPDATE knowledge SET deleted_at = now(), updated_at = now() "
            "WHERE key = ANY(%s) AND deleted_at IS NULL RETURNING id",
            [key_list],
        )
        return len(rows)
