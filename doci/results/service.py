"""Workflow-result service: persist a run's stored artifacts.

Backs the ``workflow_result`` table (raw SQL over the async :class:`Postgres`
client, mirroring :class:`doci.media.service.MediaService` and
:class:`doci.workflows.service.WorkflowExecutionService`). :meth:`save` is the
write path used by the ``SaveResultToPostgres`` activity; the read API a (future)
deepagents tool calls to understand a document's context will join it here.

The payload always lands in a single JSONB ``content`` column: a JSON ``kind``
(:attr:`ResultKind.is_json`) is parsed and stored as-is, a text kind is wrapped
as ``{"result": <text>}`` so every kind reads back uniformly.
"""

import json
from uuid import UUID

from opentelemetry.trace import SpanKind, get_current_span
from psycopg2.extras import Json, register_uuid

from doci.helpers import internal
from doci.postgres import Postgres
from doci.results.models import PageRef, ResultKind, WorkflowResultRecord
from doci.telemetry import traced, with_metrics, with_span

# Adapt uuid.UUID <-> PostgreSQL uuid (params + result columns) process-wide.
register_uuid()

_COLS = "id, execution_id, part_id, kind, content, created_at, updated_at"


@traced
class WorkflowResultService:
    """Writes over the ``workflow_result`` table."""

    def __init__(self, postgres: Postgres) -> None:
        self._pg = postgres

    @internal
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def save(
        self,
        *,
        execution_id: UUID,
        part_id: UUID,
        kind: ResultKind | str,
        payload: str,
    ) -> UUID:
        """Upsert a result for ``(execution_id, part_id, kind)``; return its id.

        Idempotent: LangGraph resume / retries re-run nodes, so a repeat save
        overwrites the existing row rather than duplicating it. An unknown
        ``kind`` raises ``ValueError`` (rather than silently storing a typo).
        """
        kind = ResultKind(kind)
        _annotate(execution_id, part_id)
        content = json.loads(payload) if kind.is_json else {"result": payload}
        return await self._pg.fetch_val(
            "INSERT INTO workflow_result (execution_id, part_id, kind, content) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (execution_id, part_id, kind) "
            "DO UPDATE SET content = EXCLUDED.content, updated_at = now() "
            "RETURNING id",
            [execution_id, part_id, str(kind), Json(content)],
        )

    # region read API (the audit/deepagents tools call these)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_results(self, execution_id: UUID) -> list[WorkflowResultRecord]:
        """All stored results for a run (any kind, any part)."""
        rows = await self._pg.fetch_all(
            f"SELECT {_COLS} FROM workflow_result WHERE execution_id = %s "
            "ORDER BY part_id, kind",
            [execution_id],
        )
        return [WorkflowResultRecord.from_row(r) for r in rows]

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get(
        self, execution_id: UUID, part_id: UUID, kind: ResultKind | str
    ) -> WorkflowResultRecord | None:
        """One result by ``(execution_id, part_id, kind)``; ``None`` if absent."""
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM workflow_result "
            "WHERE execution_id = %s AND part_id = %s AND kind = %s",
            [execution_id, part_id, str(ResultKind(kind))],
        )
        return WorkflowResultRecord.from_row(row) if row else None

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def page_index(self, execution_id: UUID) -> list[PageRef]:
        """The run's annotated pages (page order), each with its classification.

        Joins ``document_part`` for page ordering and pulls ``item_key`` /
        ``category`` out of each annotation — the compact "table of contents" an
        audit agent reasons over before pulling any full page.
        """
        rows = await self._pg.fetch_all(
            "SELECT p.id AS part_id, p.page_number, p.locator, "
            "       r.content->>'item_key' AS item_key, "
            "       r.content->>'category'  AS category "
            "FROM workflow_result r JOIN document_part p ON p.id = r.part_id "
            "WHERE r.execution_id = %s AND r.kind = %s "
            "ORDER BY p.page_number NULLS LAST, p.locator",
            [execution_id, str(ResultKind.ANNOTATION)],
        )
        return [PageRef.from_row(r) for r in rows]

    # endregion


def _annotate(execution_id: UUID, part_id: UUID) -> None:
    span = get_current_span()
    span.set_attribute("workflow.execution_id", str(execution_id))
    span.set_attribute("document.part_id", str(part_id))
