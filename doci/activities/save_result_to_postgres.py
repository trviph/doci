"""Activity: persist a workflow result to Postgres.

A ``save_result_to_*`` backend (sibling to :class:`SaveResultToDisk`) that stores
the result in the ``workflow_result`` table instead of on local disk, so it is
queryable — later a deepagents tool will read these rows to understand a
document's context. Conforms to the same ``SaveResult`` interface; returns the
row id as the ``ref`` that locates the stored result. Delegates the write (JSON
wrapping + idempotent upsert) to :class:`WorkflowResultService`.
"""

from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.results import WorkflowResultService
from doci.telemetry import traced, with_metrics, with_span


@traced
class SaveResultToPostgres:
    """Persist a workflow result to Postgres; returns the row id as the ref."""

    def __init__(self, results: WorkflowResultService) -> None:
        self._results = results

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(
        self, execution_id: UUID, part_id: UUID, kind: str, payload: str
    ) -> str:
        """Store ``payload`` for an execution's ``part_id``/``kind``; return the row id."""
        result_id = await self._results.save(
            execution_id=execution_id,
            part_id=part_id,
            kind=kind,
            payload=payload,
        )
        return str(result_id)
