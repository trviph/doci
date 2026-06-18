"""FastAPI router for knowledge entries (``/knowledge``).

CRUD over natural-language reference entries. Resolves its service from
``app.state.userdata_knowledge`` when not explicitly bound (mirroring the other
userdata submodule routers). Domain errors map to HTTP codes via :func:`_map_errors`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.knowledge.service import KnowledgeService

# region request / response models --------------------------------------------


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KnowledgeModel(_FromAttrs):
    id: UUID
    key: str
    name: str
    description: str | None
    body: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeListPageModel(_FromAttrs):
    items: list[KnowledgeModel]
    limit: int
    offset: int
    has_more: bool


class KnowledgeCreate(BaseModel):
    name: str
    body: str
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None


class KnowledgeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    body: str | None = None


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


def build_knowledge_router(bound: KnowledgeService | None = None) -> APIRouter:
    """Build the knowledge APIRouter. Resolves ``app.state.userdata_knowledge``."""
    r = APIRouter(prefix="/knowledge", tags=["knowledge"])

    def _svc(request: Request) -> KnowledgeService:
        return bound if bound is not None else request.app.state.userdata_knowledge

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Create a knowledge entry")
    async def create(
        body: KnowledgeCreate, svc: KnowledgeService = Depends(_svc)
    ) -> KnowledgeModel:
        with _map_errors():
            return KnowledgeModel.model_validate(
                await svc.create_knowledge(
                    name=body.name,
                    body=body.body,
                    key=body.key,
                    description=body.description,
                )
            )

    @r.get("", summary="List knowledge entries (paged; optional ?search=)")
    async def list_knowledge(
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        svc: KnowledgeService = Depends(_svc),
    ) -> KnowledgeListPageModel:
        return KnowledgeListPageModel.model_validate(
            await svc.list_knowledge(search=search, limit=limit, offset=offset)
        )

    @r.get("/{key}", summary="Get a knowledge entry", responses={404: {}})
    async def get_knowledge(
        key: str, svc: KnowledgeService = Depends(_svc)
    ) -> KnowledgeModel:
        with _map_errors():
            return KnowledgeModel.model_validate(await svc.get_knowledge(key))

    @r.patch("/{key}", summary="Update a knowledge entry", responses={404: {}})
    async def update_knowledge(
        key: str, body: KnowledgeUpdate, svc: KnowledgeService = Depends(_svc)
    ) -> KnowledgeModel:
        with _map_errors():
            return KnowledgeModel.model_validate(
                await svc.update_knowledge(
                    key, name=body.name, description=body.description, body=body.body
                )
            )

    @r.delete("/{key}", summary="Soft-delete a knowledge entry")
    async def delete_knowledge(
        key: str, svc: KnowledgeService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete_knowledge([key]))

    return r
