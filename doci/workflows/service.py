"""Workflow-execution service: persist + advance the lifecycle of a run.

Backs the ``workflow_execution`` table (raw SQL over the async :class:`Postgres`
client, mirroring :class:`doci.media.service.MediaService`). The API inserts a
``QUEUED`` row at trigger time; the worker tasks advance it to ``RUNNING`` and
finally ``SUCCEEDED`` / ``FAILED``. The structured ``input`` / ``result`` /
``metadata`` blobs are stored as JSONB via their versioned dataclasses.
"""

from typing import Any
from uuid import UUID, uuid4

from opentelemetry.trace import SpanKind, get_current_span
from psycopg.types.json import Jsonb

from doci.postgres import Postgres
from doci.telemetry import traced, with_metrics, with_span
from doci.workflows.models import (
    WorkflowExecutionRecord,
    WorkflowInput,
    WorkflowMetadata,
    WorkflowResult,
    WorkflowStatus,
)


_COLS = (
    "id, workflow, entity_type, entity_id, status, input, result, metadata, "
    "started_at, finished_at, created_at, updated_at"
)


class WorkflowExecutionNotFound(Exception):
    """Raised when no ``workflow_execution`` row matches the given id."""


@traced
class WorkflowExecutionService:
    """CRUD + lifecycle transitions over the ``workflow_execution`` table."""

    def __init__(self, postgres: Postgres) -> None:
        self._pg = postgres

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def create(
        self,
        *,
        workflow: str,
        entity_type: str,
        entity_id: UUID,
        input: WorkflowInput,
        metadata: WorkflowMetadata,
    ) -> UUID:
        """Insert a ``QUEUED`` execution row and return its id."""
        execution_id = uuid4()
        _annotate(execution_id)
        await self._pg.execute(
            "INSERT INTO workflow_execution "
            "(id, workflow, entity_type, entity_id, status, input, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                execution_id,
                workflow,
                entity_type,
                entity_id,
                int(WorkflowStatus.QUEUED),
                Jsonb(input.to_json()),
                Jsonb(metadata.to_json()),
            ],
        )
        return execution_id

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def set_metadata(
        self, execution_id: UUID, metadata: WorkflowMetadata
    ) -> None:
        """Overwrite the ``metadata`` blob (e.g. backfill the taskiq job id)."""
        _annotate(execution_id)
        await self._pg.execute(
            "UPDATE workflow_execution SET metadata = %s, updated_at = now() "
            "WHERE id = %s",
            [Jsonb(metadata.to_json()), execution_id],
        )

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def mark_running(self, execution_id: UUID) -> None:
        """Transition to ``RUNNING`` and stamp ``started_at``."""
        _annotate(execution_id)
        await self._pg.execute(
            "UPDATE workflow_execution "
            "SET status = %s, started_at = now(), updated_at = now() WHERE id = %s",
            [int(WorkflowStatus.RUNNING), execution_id],
        )

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def mark_succeeded(
        self, execution_id: UUID, result: WorkflowResult, metadata: WorkflowMetadata
    ) -> None:
        """Transition to ``SUCCEEDED``, storing the result + final metadata."""
        await self._finish(execution_id, WorkflowStatus.SUCCEEDED, result, metadata)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def mark_failed(
        self, execution_id: UUID, result: WorkflowResult, metadata: WorkflowMetadata
    ) -> None:
        """Transition to ``FAILED``, storing the error + final metadata."""
        await self._finish(execution_id, WorkflowStatus.FAILED, result, metadata)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def list_recent(
        self, *, workflow: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Newest-first executions, each with the name of the document it ran on.

        Pass ``workflow`` to filter by kind (e.g. ``"audit"``). Returns raw rows
        (id, workflow, entity_id, status, timestamps, document_name) — the router
        shapes them into its response model.
        """
        where = "WHERE e.workflow = %s " if workflow is not None else ""
        params: list[Any] = [workflow] if workflow is not None else []
        return await self._pg.fetch_all(
            "SELECT e.id, e.workflow, e.entity_id, e.status, e.started_at, "
            "       e.finished_at, e.created_at, d.name AS document_name "
            "FROM workflow_execution e "
            "LEFT JOIN document d "
            "  ON e.entity_type = 'document' AND d.id = e.entity_id "
            f"{where}"
            "ORDER BY e.created_at DESC, e.id "
            "LIMIT %s OFFSET %s",
            [*params, limit, offset],
        )

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get(self, execution_id: UUID) -> WorkflowExecutionRecord:
        """Fetch an execution by id."""
        _annotate(execution_id)
        row = await self._pg.fetch_one(
            f"SELECT {_COLS} FROM workflow_execution WHERE id = %s", [execution_id]
        )
        if row is None:
            raise WorkflowExecutionNotFound(str(execution_id))
        return WorkflowExecutionRecord.from_row(row)

    async def _finish(
        self,
        execution_id: UUID,
        status: WorkflowStatus,
        result: WorkflowResult,
        metadata: WorkflowMetadata,
    ) -> None:
        _annotate(execution_id)
        await self._pg.execute(
            "UPDATE workflow_execution SET status = %s, result = %s, metadata = %s, "
            "finished_at = now(), updated_at = now() WHERE id = %s",
            [
                int(status),
                Jsonb(result.to_json()),
                Jsonb(metadata.to_json()),
                execution_id,
            ],
        )


def _annotate(execution_id: UUID) -> None:
    get_current_span().set_attribute("workflow.execution_id", str(execution_id))
