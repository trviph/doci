from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.media import MediaRecord, MediaService
from doci.telemetry import traced, with_metrics, with_span


@traced
class FinalizeMedia:
    """Finalize an uploaded media through the injected `MediaService`."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, media_id: UUID) -> MediaRecord:
        """Finalize `media_id` and return the finalized record."""
        return await self._media.finalize(media_id)
