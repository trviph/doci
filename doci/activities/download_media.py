from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.media import MediaService
from doci.telemetry import traced, with_metrics, with_span


@traced
class DownloadMedia:
    """Download a media object's body as bytes through the injected `MediaService`."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, media_id: UUID) -> bytes:
        """Download `media_id` and return its full body as bytes."""
        return await self._media.download(media_id)
