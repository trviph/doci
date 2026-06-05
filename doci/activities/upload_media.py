from uuid import UUID

from doci.media import MediaRecord, MediaService, MediaType


class UploadMedia:
    """Upload preprocessed media (split pages, thumbnails, ...) through the
    injected `MediaService`, returning the stored record."""

    def __init__(self, media: MediaService) -> None:
        self._media = media

    async def __call__(
        self,
        data: bytes,
        *,
        name: str | None = None,
        parent_id: UUID | None = None,
        type: MediaType = MediaType.PAGE,
        mime_type: str | None = None,
    ) -> MediaRecord:
        """Store `data` as a new READY media row and return it."""
        return await self._media.upload(
            data, name=name, parent_id=parent_id, type=type, mime_type=mime_type
        )
