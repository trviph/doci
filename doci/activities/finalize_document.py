from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.documents import AlreadyFinalized, DocumentRecord, DocumentService
from doci.telemetry import traced, with_metrics, with_span


@traced
class FinalizeDocument:
    """Finalize an uploaded document through the injected `DocumentService`."""

    def __init__(self, documents: DocumentService) -> None:
        self._documents = documents

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, document_id: UUID) -> DocumentRecord:
        """Finalize `document_id` and return its record.

        Idempotent: if the document is already finalized (e.g. a taskiq retry of
        the workflow, or a re-submitted run), return the existing record instead
        of raising — the desired post-condition (a finalized record) already
        holds. The HTTP finalize endpoint calls ``DocumentService.finalize``
        directly and keeps its 409-on-conflict behavior.
        """
        try:
            return await self._documents.finalize(document_id)
        except AlreadyFinalized:
            return await self._documents.get(document_id)
