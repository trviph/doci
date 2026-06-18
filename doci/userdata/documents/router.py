"""FastAPI router for document definitions (``/dossiers/{dossier_key}/documents``).

Nested under a dossier (mirroring the legacy group-items UX). Resolves its service
from ``app.state.userdata_document_defs`` when not explicitly bound. Domain errors
map to HTTP codes via :func:`_map_errors`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.userdata.documents.service import DocumentDefService
from doci.userdata.errors import DuplicateKey, NotFound

# region request / response models --------------------------------------------


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentModel(_FromAttrs):
    id: UUID
    dossier_id: UUID
    key: str
    name: str
    description: str | None
    look_for: str | None
    created_at: datetime
    updated_at: datetime


class DocumentUpsert(BaseModel):
    name: str
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None
    look_for: str | None = Field(
        default=None,
        description="Optional plaintext: what to look for in this document.",
    )


class DeleteResult(BaseModel):
    deleted: int


# endregion


@contextmanager
def _map_errors() -> Iterator[None]:
    try:
        yield
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except DuplicateKey as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def build_document_defs_router(bound: DocumentDefService | None = None) -> APIRouter:
    """Build the document-definitions APIRouter. Resolves ``app.state.userdata_document_defs``."""
    r = APIRouter(prefix="/dossiers/{dossier_key}/documents", tags=["document-defs"])

    def _svc(request: Request) -> DocumentDefService:
        return bound if bound is not None else request.app.state.userdata_document_defs

    @r.get("", summary="List a dossier's document definitions", responses={404: {}})
    async def list_documents(
        dossier_key: str, svc: DocumentDefService = Depends(_svc)
    ) -> list[DocumentModel]:
        with _map_errors():
            return [
                DocumentModel.model_validate(d)
                for d in await svc.list_documents(dossier_key)
            ]

    @r.put("", summary="Create or update a document definition", responses={404: {}})
    async def upsert_document(
        dossier_key: str,
        body: DocumentUpsert,
        svc: DocumentDefService = Depends(_svc),
    ) -> DocumentModel:
        with _map_errors():
            return DocumentModel.model_validate(
                await svc.upsert_document(
                    dossier_key,
                    name=body.name,
                    key=body.key,
                    description=body.description,
                    look_for=body.look_for,
                )
            )

    @r.get("/{doc_key}", summary="Get a document definition", responses={404: {}})
    async def get_document(
        dossier_key: str, doc_key: str, svc: DocumentDefService = Depends(_svc)
    ) -> DocumentModel:
        with _map_errors():
            return DocumentModel.model_validate(
                await svc.get_document(dossier_key, doc_key)
            )

    @r.delete("/{doc_key}", summary="Delete a document definition", responses={404: {}})
    async def delete_document(
        dossier_key: str, doc_key: str, svc: DocumentDefService = Depends(_svc)
    ) -> DeleteResult:
        with _map_errors():
            return DeleteResult(deleted=await svc.delete_document(dossier_key, doc_key))

    return r
