from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.media import MediaRecord, MediaService, Render
from doci.telemetry import traced, with_metrics, with_span


@traced
class EnsureThumb:
    """Idempotently create a thumbnail blob through the injected `MediaService`.

    The thumb's object key is derived from its source blob's, so re-running skips
    both the render and the upload. The caller records the returned id against its
    document / region (the blob layer stays document-agnostic)."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, source_media_id: UUID, render: Render) -> MediaRecord:
        """Ensure the thumbnail of `source_media_id` exists; return its record."""
        return await self._media.ensure_thumb(source_media_id, render)
