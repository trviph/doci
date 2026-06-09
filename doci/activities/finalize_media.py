from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.media import AlreadyFinalized, MediaRecord, MediaService
from doci.telemetry import traced, with_metrics, with_span


@traced
class FinalizeMedia:
    """Finalize an uploaded media through the injected `MediaService`."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, media_id: UUID) -> MediaRecord:
        """Finalize `media_id` and return its record.

        Idempotent: if the media is already finalized (e.g. a taskiq retry of the
        workflow, or a re-submitted run), return the existing record instead of
        raising — the desired post-condition (a finalized record) already holds.
        The HTTP finalize endpoint calls ``MediaService.finalize`` directly and
        keeps its 409-on-conflict behavior.
        """
        try:
            return await self._media.finalize(media_id)
        except AlreadyFinalized:
            return await self._media.get(media_id)
