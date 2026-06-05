from uuid import UUID

from doci.media import MediaService


class DownloadMedia:
    """Download a media object's body as bytes through the injected `MediaService`."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    async def __call__(self, media_id: UUID) -> bytes:
        """Download `media_id` and return its full body as bytes."""
        return await self._media.download(media_id)