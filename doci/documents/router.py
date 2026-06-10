"""FastAPI router for the documents service.

Mirrors the health router: pass a `DocumentService` to bind it, or omit it to
resolve `request.app.state.documents` at request time. Domain errors map to HTTP
status codes; response shapes are documented for OpenAPI via Pydantic models.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.documents.service import (
    AlreadyFinalized,
    DocumentNotFound,
    DocumentService,
    TooLarge,
    UnsupportedType,
)


class UploadRequest(BaseModel):
    name: str | None = Field(
        default=None, description="Original filename / display name."
    )


class UploadIntentModel(BaseModel):
    id: UUID = Field(description="The new document id.")
    upload_url: str = Field(description="Presigned PUT URL to upload the bytes to.")


class DocumentRecordModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    media_id: UUID
    thumb_media_id: UUID | None
    name: str | None
    status: int = Field(description="0=new, 1=ready, 2=invalid")
    page_count: int | None
    object_key: str | None
    mime_type: str | None
    size_bytes: int | None
    deleted_at: datetime | None
    purge_after: datetime | None
    created_at: datetime
    updated_at: datetime


class MediaRecordModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    object_key: str
    mime_type: str | None
    size_bytes: int | None
    deleted_at: datetime | None
    purge_after: datetime | None
    created_at: datetime
    updated_at: datetime


class MediaViewModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media: MediaRecordModel
    view_url: str
    children: list["MediaViewModel"] = Field(default_factory=list)


class DocumentListPageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[DocumentRecordModel]
    limit: int
    offset: int
    has_more: bool


class DeleteRequest(BaseModel):
    ids: list[UUID] = Field(description="Document ids to soft-delete.")


class DeleteResult(BaseModel):
    deleted: int = Field(description="Number of documents soft-deleted.")


@contextmanager
def _map_errors() -> Iterator[None]:
    try:
        yield
    except DocumentNotFound as exc:
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


def build_documents_router(documents: DocumentService | None = None) -> APIRouter:
    """Build the documents APIRouter. Resolves `app.state.documents` when not bound."""
    router = APIRouter(prefix="/documents", tags=["documents"])

    def _svc(request: Request) -> DocumentService:
        return documents if documents is not None else request.app.state.documents

    @router.post(
        "", status_code=status.HTTP_201_CREATED, summary="Request an upload URL"
    )
    async def request_upload(
        body: UploadRequest | None = None, svc: DocumentService = Depends(_svc)
    ) -> UploadIntentModel:
        body = body or UploadRequest()
        intent = await svc.request_upload(name=body.name)
        return UploadIntentModel(id=intent.id, upload_url=intent.upload_url)

    @router.get("", summary="List documents (paged)")
    async def list_documents(
        limit: int | None = None, offset: int = 0, svc: DocumentService = Depends(_svc)
    ) -> DocumentListPageModel:
        return DocumentListPageModel.model_validate(
            await svc.list_documents(limit=limit, offset=offset)
        )

    @router.post(
        "/{document_id}/finalize",
        summary="Finalize an upload (validate + mark ready)",
        responses={404: {}, 409: {}, 413: {}, 415: {}},
    )
    async def finalize(
        document_id: UUID, svc: DocumentService = Depends(_svc)
    ) -> DocumentRecordModel:
        with _map_errors():
            return DocumentRecordModel.model_validate(await svc.finalize(document_id))

    @router.get(
        "/{document_id}/view",
        summary="View URLs for the original + its pages",
        responses={404: {}},
    )
    async def get_view(
        document_id: UUID, svc: DocumentService = Depends(_svc)
    ) -> MediaViewModel:
        with _map_errors():
            return MediaViewModel.model_validate(await svc.get_view(document_id))

    @router.get(
        "/{document_id}/view/thumb",
        summary="View URLs for the thumb of the original + each page",
        responses={404: {}},
    )
    async def get_view_thumb(
        document_id: UUID, svc: DocumentService = Depends(_svc)
    ) -> MediaViewModel:
        with _map_errors():
            return MediaViewModel.model_validate(await svc.get_view_thumb(document_id))

    @router.delete("/{document_id}", summary="Soft-delete one document")
    async def delete_one(
        document_id: UUID, svc: DocumentService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete([document_id]))

    @router.delete("", summary="Soft-delete many documents")
    async def delete_many(
        body: DeleteRequest = Body(...), svc: DocumentService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete(body.ids))

    return router