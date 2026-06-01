"""FastAPI router for the media service.

Mirrors the health router: pass a `MediaService` to bind it, or omit it to
resolve `request.app.state.media` at request time. Domain errors map to HTTP
status codes; response shapes are documented for OpenAPI via Pydantic models.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.media.service import (
    AlreadyFinalized,
    MediaNotFound,
    MediaService,
    TooLarge,
    UnsupportedType,
)


class UploadRequest(BaseModel):
    name: str | None = Field(
        default=None, description="Original filename / display name."
    )
    parent_id: UUID | None = Field(
        default=None, description="Parent media id, for derivatives."
    )


class UploadIntentModel(BaseModel):
    id: UUID
    upload_url: str = Field(description="Presigned PUT URL to upload the bytes to.")


class MediaRecordModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    type: int = Field(description="0=original, 1=thumb, 2=page")
    object_key: str
    name: str | None
    mime_type: str | None
    size_bytes: int | None
    status: int = Field(description="0=new, 1=ready, 2=invalid")
    deleted_at: datetime | None
    purge_after: datetime | None
    created_at: datetime
    updated_at: datetime


class MediaViewModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media: MediaRecordModel
    view_url: str
    children: list["MediaViewModel"] = Field(default_factory=list)


class MediaListPageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[MediaRecordModel]
    limit: int
    offset: int
    has_more: bool


class DeleteRequest(BaseModel):
    ids: list[UUID] = Field(
        description="Media ids to soft-delete (with their descendants)."
    )


class DeleteResult(BaseModel):
    deleted: int = Field(description="Number of rows soft-deleted.")


@contextmanager
def _map_errors() -> Iterator[None]:
    try:
        yield
    except MediaNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except AlreadyFinalized as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "already finalized") from exc
    except UnsupportedType as exc:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported type"
        ) from exc
    except TooLarge as exc:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "too large"
        ) from exc


def build_media_router(media: MediaService | None = None) -> APIRouter:
    """Build the media APIRouter. Resolves `app.state.media` when not bound."""
    router = APIRouter(prefix="/media", tags=["media"])

    def _svc(request: Request) -> MediaService:
        return media if media is not None else request.app.state.media

    @router.post(
        "", status_code=status.HTTP_201_CREATED, summary="Request an upload URL"
    )
    async def request_upload(
        body: UploadRequest | None = None, svc: MediaService = Depends(_svc)
    ) -> UploadIntentModel:
        body = body or UploadRequest()
        intent = await svc.request_upload(name=body.name, parent_id=body.parent_id)
        return UploadIntentModel(id=intent.id, upload_url=intent.upload_url)

    @router.get("", summary="List originals (paged)")
    async def list_media(
        limit: int | None = None, offset: int = 0, svc: MediaService = Depends(_svc)
    ) -> MediaListPageModel:
        return MediaListPageModel.model_validate(
            await svc.list_media(limit=limit, offset=offset)
        )

    @router.post(
        "/{media_id}/finalize",
        summary="Finalize an upload (validate + mark ready)",
        responses={404: {}, 409: {}, 413: {}, 415: {}},
    )
    async def finalize(
        media_id: UUID, svc: MediaService = Depends(_svc)
    ) -> MediaRecordModel:
        with _map_errors():
            return MediaRecordModel.model_validate(await svc.finalize(media_id))

    @router.get(
        "/{media_id}/view",
        summary="View URLs for the original + its pages",
        responses={404: {}},
    )
    async def get_view(
        media_id: UUID, svc: MediaService = Depends(_svc)
    ) -> MediaViewModel:
        with _map_errors():
            return MediaViewModel.model_validate(await svc.get_view(media_id))

    @router.get(
        "/{media_id}/view/thumb",
        summary="View URLs for the thumb of the original + each page",
        responses={404: {}},
    )
    async def get_view_thumb(
        media_id: UUID, svc: MediaService = Depends(_svc)
    ) -> MediaViewModel:
        with _map_errors():
            return MediaViewModel.model_validate(await svc.get_view_thumb(media_id))

    @router.delete("/{media_id}", summary="Soft-delete one media (and descendants)")
    async def delete_one(
        media_id: UUID, svc: MediaService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete([media_id]))

    @router.delete("", summary="Soft-delete many media (and descendants)")
    async def delete_many(
        body: DeleteRequest = Body(...), svc: MediaService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete(body.ids))

    return router
