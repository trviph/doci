"""Audit-rule service: structured rules with a tagged-union check body.

Owns ``audit_rule``. :meth:`applicable_to` is the selector-matching read the
(future) audit agent calls — the diagram's ``get_user_rule(type)``. The ``check``
union (``prompt`` | ``expr``) is stored and validated here; only ``prompt`` is
evaluated downstream in v1.
"""

from collections.abc import Sequence

from opentelemetry.trace import SpanKind
from psycopg2 import errors as pg_errors
from psycopg2.extras import Json, register_uuid

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.models import (
    AuditRule,
    CheckExpr,
    CheckPrompt,
    ListPage,
    Selector,
    Severity,
    gen_key,
)

register_uuid()

_DEFAULT_PAGE = 50
_MAX_PAGE = 200

_RULE_COLS = (
    "id, key, name, description, applies_to, reference_keys, check_body, "
    "severity, enabled, deleted_at, created_at, updated_at"
)

# Match enabled, non-deleted rules that are global (no selectors) OR have a
# selector satisfied by the (group, document) query: every field the selector
# sets must equal the corresponding query value.
_APPLIES = (
    "enabled = true AND deleted_at IS NULL AND ("
    "  jsonb_array_length(applies_to) = 0 OR EXISTS ("
    "    SELECT 1 FROM jsonb_array_elements(applies_to) sel "
    "    WHERE (sel->>'group' IS NULL OR sel->>'group' = %s) "
    "      AND (sel->>'document' IS NULL OR sel->>'document' = %s)"
    "  )"
    ")"
)


def _selectors_json(selectors: Sequence[Selector] | None) -> Json:
    return Json([s.model_dump() for s in (selectors or [])])


@traced
class AuditRuleService:
    """The audit-rule domain over ``audit_rule``."""

    def __init__(self, *, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_rules(
        self, *, limit: int | None = None, offset: int = 0
    ) -> ListPage:
        """List rules (newest first), paginated."""
        lim = max(1, min(limit or _DEFAULT_PAGE, _MAX_PAGE))
        off = max(0, offset)
        rows = await self._pg.fetch_all(
            f"SELECT {_RULE_COLS} FROM audit_rule WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
            [lim + 1, off],
        )
        has_more = len(rows) > lim
        items = [AuditRule.from_row(r) for r in rows[:lim]]
        return ListPage(items=items, limit=lim, offset=off, has_more=has_more)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_rule(self, key: str) -> AuditRule:
        row = await self._pg.fetch_one(
            f"SELECT {_RULE_COLS} FROM audit_rule "
            "WHERE key = %s AND deleted_at IS NULL",
            [key],
        )
        if row is None:
            raise NotFound(f"audit_rule {key!r}")
        return AuditRule.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def applicable_to(
        self, *, group: str | None = None, document: str | None = None
    ) -> list[AuditRule]:
        """Rules that apply to a ``group`` and/or ``document`` (key), plus globals.

        Highest severity first, so a caller surfaces blocking rules before notes.
        """
        rows = await self._pg.fetch_all(
            f"SELECT {_RULE_COLS} FROM audit_rule WHERE {_APPLIES} "
            "ORDER BY severity DESC, key",
            [group, document],
        )
        return [AuditRule.from_row(r) for r in rows]

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create_rule(
        self,
        *,
        name: str,
        check: CheckPrompt | CheckExpr,
        key: str | None = None,
        description: str | None = None,
        applies_to: Sequence[Selector] | None = None,
        reference_keys: Sequence[str] | None = None,
        severity: Severity = Severity.INFO,
        enabled: bool = True,
    ) -> AuditRule:
        """Create a rule. ``key`` defaults to a slug derived from ``name``."""
        key = key or gen_key(name)
        try:
            row = await self._pg.fetch_one(
                "INSERT INTO audit_rule "
                "(key, name, description, applies_to, reference_keys, check_body, "
                " severity, enabled) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                f"RETURNING {_RULE_COLS}",
                [
                    key,
                    name,
                    description,
                    _selectors_json(applies_to),
                    Json(list(reference_keys or [])),
                    Json(check.model_dump()),
                    int(severity),
                    enabled,
                ],
            )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateKey(f"audit_rule {key!r}") from exc
        return AuditRule.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def update_rule(
        self,
        key: str,
        *,
        name: str | None = None,
        description: str | None = None,
        applies_to: Sequence[Selector] | None = None,
        reference_keys: Sequence[str] | None = None,
        check: CheckPrompt | CheckExpr | None = None,
        severity: Severity | None = None,
        enabled: bool | None = None,
    ) -> AuditRule:
        """Patch a rule; ``None`` arguments leave the column unchanged."""
        row = await self._pg.fetch_one(
            "UPDATE audit_rule SET "
            "name = COALESCE(%s, name), "
            "description = COALESCE(%s, description), "
            "applies_to = COALESCE(%s, applies_to), "
            "reference_keys = COALESCE(%s, reference_keys), "
            "check_body = COALESCE(%s, check_body), "
            "severity = COALESCE(%s, severity), "
            "enabled = COALESCE(%s, enabled), "
            "updated_at = now() "
            f"WHERE key = %s AND deleted_at IS NULL RETURNING {_RULE_COLS}",
            [
                name,
                description,
                _selectors_json(applies_to) if applies_to is not None else None,
                Json(list(reference_keys)) if reference_keys is not None else None,
                Json(check.model_dump()) if check is not None else None,
                int(severity) if severity is not None else None,
                enabled,
                key,
            ],
        )
        if row is None:
            raise NotFound(f"audit_rule {key!r}")
        return AuditRule.from_row(row)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def delete_rules(self, keys: Sequence[str]) -> int:
        """Soft-delete rules by key. Returns the count."""
        key_list = list(keys)
        if not key_list:
            return 0
        rows = await self._pg.fetch_all(
            "UPDATE audit_rule SET deleted_at = now(), updated_at = now() "
            "WHERE key = ANY(%s) AND deleted_at IS NULL RETURNING id",
            [key_list],
        )
        return len(rows)
