"""Agent-rule service: markdown rules + their m‑n link to dossiers.

Owns ``agent_rule`` and the ``agent_rule_dossier`` join. CRUD with stable slug
keys and soft delete; the link is managed from the rule side
(:meth:`set_dossiers`) and read in both directions (:meth:`dossiers_for_rule`,
:meth:`rules_for_dossier`).
"""

from collections.abc import Sequence

from opentelemetry.trace import SpanKind
from psycopg import errors as pg_errors

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.common import ListPage, _page_bounds, gen_key
from doci.userdata.dossiers.models import DossierDef
from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.rules.models import AgentRule


_COLS = "id, key, name, body, deleted_at, created_at, updated_at"
_DOSSIER_COLS = "id, key, name, description, deleted_at, created_at, updated_at"


@traced
class AgentRuleService:
    """The agent-rule domain over ``agent_rule`` + ``agent_rule_dossier``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_rules(
        self, *, limit: int | None = None, offset: int = 0
    ) -> ListPage:
        """List rules (newest first), paginated."""
        lim, off = _page_bounds(limit, offset)
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM agent_rule WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
            [lim + 1, off],
        )
        has_more = len(rows) > lim
        items = [AgentRule.from_row(r) for r in rows[:lim]]
        return ListPage(items=items, limit=lim, offset=off, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_rule(self, key: str) -> AgentRule:
        """Fetch one rule by key."""
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM agent_rule WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"agent_rule {key!r}")
        return AgentRule.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create_rule(
        self, *, name: str, body: str, key: str | None = None
    ) -> AgentRule:
        """Create a rule. ``key`` defaults to a slug derived from ``name``."""
        key = key or gen_key(name)
        try:
            row = await self._pg.fetch_one(
                f"INSERT INTO agent_rule (key, name, body) "
                f"VALUES (%s, %s, %s) RETURNING {_COLS}",
                [key, name, body],
            )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateKey(f"agent_rule {key!r}") from exc
        return AgentRule.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def update_rule(
        self, key: str, *, name: str | None = None, body: str | None = None
    ) -> AgentRule:
        """Patch a rule's name/body (None = leave unchanged)."""
        row = await self._pg.fetch_one(
            "UPDATE agent_rule SET "
            "name = COALESCE(%s, name), "
            "body = COALESCE(%s, body), "
            "updated_at = now() "
            f"WHERE key = %s AND deleted_at IS NULL RETURNING {_COLS}",
            [name, body, key],
        )
        if row is None:
            raise NotFound(f"agent_rule {key!r}")
        return AgentRule.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_rules(self, keys: Sequence[str]) -> int:
        """Soft-delete rules by key. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        rows = await self._pg.fetch_all(
            "UPDATE agent_rule SET deleted_at = now(), updated_at = now() "
            "WHERE key = ANY(%s) AND deleted_at IS NULL RETURNING id",
            [key_list],
        )
        return len(rows)

    # region dossier links (m‑n)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def set_dossiers(self, rule_key: str, dossier_keys: Sequence[str]) -> int:
        """Replace the rule's linked dossiers with ``dossier_keys`` (transactional).

        Returns the number of links after the operation. Raises :class:`NotFound`
        if the rule or any supplied dossier key is unknown.
        """
        wanted = list(dict.fromkeys(dossier_keys))  # de-dupe, keep order
        async with self._pg.transaction() as tx:
            rule = await tx.fetch_one(
                "SELECT id FROM agent_rule WHERE key = %s AND deleted_at IS NULL",
                [rule_key],
            )
            if rule is None:
                raise NotFound(f"agent_rule {rule_key!r}")
            dossier_ids: list = []
            if wanted:
                rows = await tx.fetch_all(
                    "SELECT id, key FROM dossier_def "
                    "WHERE key = ANY(%s) AND deleted_at IS NULL",
                    [wanted],
                )
                found = {r["key"]: r["id"] for r in rows}
                missing = [k for k in wanted if k not in found]
                if missing:
                    raise NotFound(f"dossier_def {missing[0]!r}")
                dossier_ids = [found[k] for k in wanted]
            await tx.execute(
                "DELETE FROM agent_rule_dossier WHERE rule_id = %s", [rule["id"]]
            )
            for did in dossier_ids:
                await tx.execute(
                    "INSERT INTO agent_rule_dossier (rule_id, dossier_id) "
                    "VALUES (%s, %s)",
                    [rule["id"], did],
                )
        return len(dossier_ids)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def dossiers_for_rule(self, rule_key: str) -> list[DossierDef]:
        """List the (non-deleted) dossiers a rule is linked to."""
        rule = await self._pg.fetch_one(
            "SELECT id FROM agent_rule WHERE key = %s AND deleted_at IS NULL",
            [rule_key],
        )
        if rule is None:
            raise NotFound(f"agent_rule {rule_key!r}")
        rows = await self._pg.fetch_all(
            f"SELECT {', '.join('d.' + c for c in _DOSSIER_COLS.split(', '))} "
            "FROM agent_rule_dossier l JOIN dossier_def d ON d.id = l.dossier_id "
            "WHERE l.rule_id = %s AND d.deleted_at IS NULL "
            "ORDER BY d.created_at DESC, d.id",
            [rule["id"]],
        )
        return [DossierDef.from_row(r) for r in rows]

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def rules_for_dossier(self, dossier_key: str) -> list[AgentRule]:
        """List the (non-deleted) rules linked to a dossier."""
        dossier = await self._pg.fetch_one(
            "SELECT id FROM dossier_def WHERE key = %s AND deleted_at IS NULL",
            [dossier_key],
        )
        if dossier is None:
            raise NotFound(f"dossier_def {dossier_key!r}")
        rows = await self._pg.fetch_all(
            f"SELECT {', '.join('r.' + c for c in _COLS.split(', '))} "
            "FROM agent_rule_dossier l JOIN agent_rule r ON r.id = l.rule_id "
            "WHERE l.dossier_id = %s AND r.deleted_at IS NULL "
            "ORDER BY r.created_at DESC, r.id",
            [dossier["id"]],
        )
        return [AgentRule.from_row(r) for r in rows]

    # endregion
