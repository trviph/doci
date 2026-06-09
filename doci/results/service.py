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
from doci.results.models import ResultKind
from doci.telemetry import traced, with_metrics, with_span

# Adapt uuid.UUID <-> PostgreSQL uuid (params + result columns) process-wide.
register_uuid()


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
        media_id: UUID,
        kind: ResultKind | str,
        payload: str,
    ) -> UUID:
        """Upsert a result for ``(execution_id, media_id, kind)``; return its id.

        Idempotent: LangGraph resume / retries re-run nodes, so a repeat save
        overwrites the existing row rather than duplicating it. An unknown
        ``kind`` raises ``ValueError`` (rather than silently storing a typo).
        """
        kind = ResultKind(kind)
        _annotate(execution_id, media_id)
        content = json.loads(payload) if kind.is_json else {"result": payload}
        return await self._pg.fetch_val(
            "INSERT INTO workflow_result (execution_id, media_id, kind, content) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (execution_id, media_id, kind) "
            "DO UPDATE SET content = EXCLUDED.content, updated_at = now() "
            "RETURNING id",
            [execution_id, media_id, str(kind), Json(content)],
        )


def _annotate(execution_id: UUID, media_id: UUID) -> None:
    span = get_current_span()
    span.set_attribute("workflow.execution_id", str(execution_id))
    span.set_attribute("media.id", str(media_id))
