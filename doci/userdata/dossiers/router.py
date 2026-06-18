"""FastAPI router for dossier definitions (``/dossiers``).

CRUD over dossiers, plus the reverse m‑n read ``GET /dossiers/{key}/rules`` which
resolves the agent-rule service from ``app.state.userdata_agent_rules``. The
dossier service itself resolves from ``app.state.userdata_dossiers`` when not
explicitly bound. Domain errors map to HTTP codes via :func:`_map_errors`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.userdata.dossiers.service import DossierService
from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.rules.router import RuleModel

# region request / response models --------------------------------------------


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DossierModel(_FromAttrs):
    id: UUID
    key: str
    name: str
    description: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DossierListPageModel(_FromAttrs):
    items: list[DossierModel]
    limit: int
    offset: int
    has_more: bool


class DossierCreate(BaseModel):
    name: str
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None


class DossierUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


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


def build_dossiers_router(bound: DossierService | None = None) -> APIRouter:
    """Build the dossiers APIRouter. Resolves ``app.state.userdata_dossiers``."""
    r = APIRouter(prefix="/dossiers", tags=["dossiers"])

    def _svc(request: Request) -> DossierService:
        return bound if bound is not None else request.app.state.userdata_dossiers

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Create a dossier")
    async def create(
        body: DossierCreate, svc: DossierService = Depends(_svc)
    ) -> DossierModel:
        with _map_errors():
            return DossierModel.model_validate(
                await svc.create_dossier(
                    name=body.name, key=body.key, description=body.description
                )
            )

    @r.get("", summary="List dossiers (paged)")
    async def list_dossiers(
        limit: int | None = None,
        offset: int = 0,
        svc: DossierService = Depends(_svc),
    ) -> DossierListPageModel:
        return DossierListPageModel.model_validate(
            await svc.list_dossiers(limit=limit, offset=offset)
        )

    @r.get("/{key}", summary="Get a dossier", responses={404: {}})
    async def get_dossier(
        key: str, svc: DossierService = Depends(_svc)
    ) -> DossierModel:
        with _map_errors():
            return DossierModel.model_validate(await svc.get_dossier(key))

    @r.patch("/{key}", summary="Update a dossier", responses={404: {}})
    async def update_dossier(
        key: str, body: DossierUpdate, svc: DossierService = Depends(_svc)
    ) -> DossierModel:
        with _map_errors():
            return DossierModel.model_validate(
                await svc.update_dossier(
                    key, name=body.name, description=body.description
                )
            )

    @r.delete("/{key}", summary="Soft-delete a dossier")
    async def delete_dossier(
        key: str, svc: DossierService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete_dossiers([key]))

    @r.get(
        "/{key}/rules",
        summary="List the agent rules that apply to this dossier",
        responses={404: {}},
    )
    async def list_rules(key: str, request: Request) -> list[RuleModel]:
        rules_svc = request.app.state.userdata_agent_rules
        with _map_errors():
            return [
                RuleModel.model_validate(rule)
                for rule in await rules_svc.rules_for_dossier(key)
            ]

    return r
