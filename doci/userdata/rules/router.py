"""FastAPI router for agent rules (``/agent-rules``).

CRUD over rules plus the m‑n link to dossiers. Resolves its service from
``app.state.userdata_agent_rules`` when not explicitly bound (mirroring the
documents router). Domain errors map to HTTP codes via :func:`_map_errors`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from doci.userdata.errors import DuplicateKey, NotFound
from doci.userdata.rules.service import AgentRuleService

# region request / response models --------------------------------------------


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RuleModel(_FromAttrs):
    id: UUID
    key: str
    name: str
    body: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuleListPageModel(_FromAttrs):
    items: list[RuleModel]
    limit: int
    offset: int
    has_more: bool


class LinkedDossierModel(_FromAttrs):
    """A dossier as returned by the rule's link listing."""

    id: UUID
    key: str
    name: str
    description: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuleCreate(BaseModel):
    name: str
    body: str
    key: str | None = None


class RuleUpdate(BaseModel):
    name: str | None = None
    body: str | None = None


class SetDossiers(BaseModel):
    dossier_keys: list[str]


class DeleteResult(BaseModel):
    deleted: int


class LinkResult(BaseModel):
    linked: int


# endregion


@contextmanager
def _map_errors() -> Iterator[None]:
    try:
        yield
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except DuplicateKey as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def build_agent_rules_router(bound: AgentRuleService | None = None) -> APIRouter:
    """Build the agent-rules APIRouter. Resolves ``app.state.userdata_agent_rules``."""
    r = APIRouter(prefix="/agent-rules", tags=["agent-rules"])

    def _svc(request: Request) -> AgentRuleService:
        return bound if bound is not None else request.app.state.userdata_agent_rules

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Create an agent rule")
    async def create(
        body: RuleCreate, svc: AgentRuleService = Depends(_svc)
    ) -> RuleModel:
        with _map_errors():
            return RuleModel.model_validate(
                await svc.create_rule(name=body.name, body=body.body, key=body.key)
            )

    @r.get("", summary="List agent rules (paged)")
    async def list_rules(
        limit: int | None = None,
        offset: int = 0,
        svc: AgentRuleService = Depends(_svc),
    ) -> RuleListPageModel:
        return RuleListPageModel.model_validate(
            await svc.list_rules(limit=limit, offset=offset)
        )

    @r.get("/{key}", summary="Get an agent rule", responses={404: {}})
    async def get_rule(key: str, svc: AgentRuleService = Depends(_svc)) -> RuleModel:
        with _map_errors():
            return RuleModel.model_validate(await svc.get_rule(key))

    @r.patch("/{key}", summary="Update an agent rule", responses={404: {}})
    async def update_rule(
        key: str, body: RuleUpdate, svc: AgentRuleService = Depends(_svc)
    ) -> RuleModel:
        with _map_errors():
            return RuleModel.model_validate(
                await svc.update_rule(key, name=body.name, body=body.body)
            )

    @r.delete("/{key}", summary="Soft-delete an agent rule")
    async def delete_rule(
        key: str, svc: AgentRuleService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete_rules([key]))

    @r.put(
        "/{key}/dossiers",
        summary="Set the dossiers this rule applies to",
        responses={404: {}},
    )
    async def set_dossiers(
        key: str, body: SetDossiers, svc: AgentRuleService = Depends(_svc)
    ) -> LinkResult:
        with _map_errors():
            return LinkResult(linked=await svc.set_dossiers(key, body.dossier_keys))

    @r.get(
        "/{key}/dossiers",
        summary="List the dossiers this rule applies to",
        responses={404: {}},
    )
    async def list_dossiers(
        key: str, svc: AgentRuleService = Depends(_svc)
    ) -> list[LinkedDossierModel]:
        with _map_errors():
            return [
                LinkedDossierModel.model_validate(d)
                for d in await svc.dossiers_for_rule(key)
            ]

    return r
