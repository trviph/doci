from uuid import UUID

from doci.media import MediaRecord, MediaService


class FinalizeMedia:
    """Finalize an uploaded media through the injected `MediaService`."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    async def __call__(self, media_id: UUID) -> MediaRecord:
        """Finalize `media_id` and return the finalized record."""
        return await self._media.finalize(media_id)
