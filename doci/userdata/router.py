"""FastAPI router for the user data layer.

One :func:`build_userdata_router` mounts three sub-routers — ``/document-groups``,
``/audit-rules``, ``/reference-data`` — each resolving its service from
``app.state`` when not explicitly bound (mirroring the documents router). Domain
errors map to HTTP codes via :func:`_map_errors`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.activities.fields import FieldSpec
from doci.userdata.errors import DuplicateKey, NotFound, SchemaViolation, UnknownField
from doci.userdata.groups_service import DocumentGroupService
from doci.userdata.models import (
    CheckExpr,
    CheckPrompt,
    FieldDef,
    Selector,
    Severity,
)
from doci.userdata.refdata_service import ReferenceDataService
from doci.userdata.rules_service import AuditRuleService

Check = CheckPrompt | CheckExpr

# region request / response models --------------------------------------------


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GroupItemModel(_FromAttrs):
    id: UUID
    group_id: UUID
    key: str
    name: str
    description: str | None
    fields: list[FieldSpec]
    required: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class GroupModel(_FromAttrs):
    id: UUID
    key: str
    name: str
    description: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[GroupItemModel] = Field(default_factory=list)


class GroupListPageModel(_FromAttrs):
    items: list[GroupModel]
    limit: int
    offset: int
    has_more: bool


class GroupCreate(BaseModel):
    name: str
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ItemUpsert(BaseModel):
    name: str
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None
    fields: list[FieldSpec] = Field(default_factory=list)
    required: bool = True
    sort_order: int = 0


class RuleModel(_FromAttrs):
    id: UUID
    key: str
    name: str
    description: str | None
    applies_to: list[Selector]
    reference_keys: list[str]
    check: Check = Field(discriminator="type")
    severity: int = Field(description="0=info, 1=warn, 2=block")
    enabled: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuleListPageModel(_FromAttrs):
    items: list[RuleModel]
    limit: int
    offset: int
    has_more: bool


class RuleCreate(BaseModel):
    name: str
    check: Check = Field(discriminator="type")
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None
    applies_to: list[Selector] = Field(default_factory=list)
    reference_keys: list[str] = Field(default_factory=list)
    severity: int = 0
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    applies_to: list[Selector] | None = None
    reference_keys: list[str] | None = None
    # No discriminator on the Optional union — pydantic resolves it by the "type"
    # literal in smart mode; an explicit discriminator rejects the None branch.
    check: Check | None = None
    severity: int | None = None
    enabled: bool | None = None


class DatasetModel(_FromAttrs):
    id: UUID
    key: str
    name: str
    description: str | None
    field_schema: list[FieldDef]
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DatasetInfoModel(_FromAttrs):
    key: str
    name: str
    description: str | None
    field_schema: list[FieldDef]
    record_count: int


class DatasetCreate(BaseModel):
    name: str
    field_schema: list[FieldDef] = Field(default_factory=list)
    key: str | None = Field(default=None, description="Defaults to a slug of name.")
    description: str | None = None


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    field_schema: list[FieldDef] | None = None


class RecordModel(_FromAttrs):
    id: UUID
    dataset_id: UUID
    key: str | None
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RecordListPageModel(_FromAttrs):
    items: list[RecordModel]
    limit: int
    offset: int
    has_more: bool


class RecordUpsert(BaseModel):
    key: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class BulkUpsert(BaseModel):
    records: list[RecordUpsert]


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
    except SchemaViolation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except UnknownField as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def build_userdata_router(
    *,
    groups: DocumentGroupService | None = None,
    rules: AuditRuleService | None = None,
    refdata: ReferenceDataService | None = None,
) -> APIRouter:
    """Build the user-data APIRouter (3 sub-routers). Resolves ``app.state.*``."""
    router = APIRouter(tags=["userdata"])
    router.include_router(_groups_router(groups))
    router.include_router(_rules_router(rules))
    router.include_router(_refdata_router(refdata))
    return router


# region document-groups ------------------------------------------------------


def _groups_router(bound: DocumentGroupService | None) -> APIRouter:
    r = APIRouter(prefix="/document-groups", tags=["document-groups"])

    def _svc(request: Request) -> DocumentGroupService:
        return bound if bound is not None else request.app.state.userdata_groups

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Create a document group")
    async def create(
        body: GroupCreate, svc: DocumentGroupService = Depends(_svc)
    ) -> GroupModel:
        with _map_errors():
            return GroupModel.model_validate(
                await svc.create_group(
                    name=body.name, key=body.key, description=body.description
                )
            )

    @r.get("", summary="List document groups (paged)")
    async def list_groups(
        limit: int | None = None,
        offset: int = 0,
        svc: DocumentGroupService = Depends(_svc),
    ) -> GroupListPageModel:
        return GroupListPageModel.model_validate(
            await svc.list_groups(limit=limit, offset=offset)
        )

    @r.get("/{key}", summary="Get a group with its items", responses={404: {}})
    async def get_group(
        key: str, svc: DocumentGroupService = Depends(_svc)
    ) -> GroupModel:
        with _map_errors():
            return GroupModel.model_validate(await svc.get_group(key))

    @r.patch("/{key}", summary="Update a group", responses={404: {}})
    async def update_group(
        key: str, body: GroupUpdate, svc: DocumentGroupService = Depends(_svc)
    ) -> GroupModel:
        with _map_errors():
            return GroupModel.model_validate(
                await svc.update_group(
                    key, name=body.name, description=body.description
                )
            )

    @r.delete("/{key}", summary="Soft-delete a group")
    async def delete_group(
        key: str, svc: DocumentGroupService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete_groups([key]))

    @r.get("/{key}/items", summary="List a group's items", responses={404: {}})
    async def list_items(
        key: str, svc: DocumentGroupService = Depends(_svc)
    ) -> list[GroupItemModel]:
        with _map_errors():
            return [GroupItemModel.model_validate(i) for i in await svc.list_items(key)]

    @r.put("/{key}/items", summary="Create or update an item", responses={404: {}})
    async def upsert_item(
        key: str, body: ItemUpsert, svc: DocumentGroupService = Depends(_svc)
    ) -> GroupItemModel:
        with _map_errors():
            return GroupItemModel.model_validate(
                await svc.upsert_item(
                    key,
                    name=body.name,
                    key=body.key,
                    description=body.description,
                    fields=body.fields,
                    required=body.required,
                    sort_order=body.sort_order,
                )
            )

    @r.delete("/{key}/items/{item_key}", summary="Delete an item", responses={404: {}})
    async def delete_item(
        key: str, item_key: str, svc: DocumentGroupService = Depends(_svc)
    ) -> DeleteResult:
        with _map_errors():
            return DeleteResult(deleted=await svc.delete_item(key, item_key))

    return r


# endregion

# region audit-rules ----------------------------------------------------------


def _rules_router(bound: AuditRuleService | None) -> APIRouter:
    r = APIRouter(prefix="/audit-rules", tags=["audit-rules"])

    def _svc(request: Request) -> AuditRuleService:
        return bound if bound is not None else request.app.state.userdata_rules

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Create an audit rule")
    async def create(
        body: RuleCreate, svc: AuditRuleService = Depends(_svc)
    ) -> RuleModel:
        with _map_errors():
            return RuleModel.model_validate(
                await svc.create_rule(
                    name=body.name,
                    check=body.check,
                    key=body.key,
                    description=body.description,
                    applies_to=body.applies_to,
                    reference_keys=body.reference_keys,
                    severity=Severity(body.severity),
                    enabled=body.enabled,
                )
            )

    @r.get("", summary="List audit rules (paged)")
    async def list_rules(
        limit: int | None = None,
        offset: int = 0,
        svc: AuditRuleService = Depends(_svc),
    ) -> RuleListPageModel:
        return RuleListPageModel.model_validate(
            await svc.list_rules(limit=limit, offset=offset)
        )

    @r.get(
        "/applicable",
        summary="Rules applicable to a group and/or document (+ globals)",
    )
    async def applicable(
        group: str | None = None,
        document: str | None = None,
        svc: AuditRuleService = Depends(_svc),
    ) -> list[RuleModel]:
        rules = await svc.applicable_to(group=group, document=document)
        return [RuleModel.model_validate(rule) for rule in rules]

    @r.get("/{key}", summary="Get an audit rule", responses={404: {}})
    async def get_rule(key: str, svc: AuditRuleService = Depends(_svc)) -> RuleModel:
        with _map_errors():
            return RuleModel.model_validate(await svc.get_rule(key))

    @r.patch("/{key}", summary="Update an audit rule", responses={404: {}})
    async def update_rule(
        key: str, body: RuleUpdate, svc: AuditRuleService = Depends(_svc)
    ) -> RuleModel:
        with _map_errors():
            return RuleModel.model_validate(
                await svc.update_rule(
                    key,
                    name=body.name,
                    description=body.description,
                    applies_to=body.applies_to,
                    reference_keys=body.reference_keys,
                    check=body.check,
                    severity=Severity(body.severity)
                    if body.severity is not None
                    else None,
                    enabled=body.enabled,
                )
            )

    @r.delete("/{key}", summary="Soft-delete an audit rule")
    async def delete_rule(
        key: str, svc: AuditRuleService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete_rules([key]))

    return r


# endregion

# region reference-data -------------------------------------------------------

_RESERVED_QUERY = {"search", "limit", "offset"}


def _refdata_router(bound: ReferenceDataService | None) -> APIRouter:
    r = APIRouter(prefix="/reference-data", tags=["reference-data"])

    def _svc(request: Request) -> ReferenceDataService:
        return bound if bound is not None else request.app.state.userdata_refdata

    @r.get("", summary="Discover datasets (schema + record count)")
    async def list_datasets(
        svc: ReferenceDataService = Depends(_svc),
    ) -> list[DatasetInfoModel]:
        return [DatasetInfoModel.model_validate(d) for d in await svc.list_datasets()]

    @r.post("", status_code=status.HTTP_201_CREATED, summary="Create a dataset")
    async def create_dataset(
        body: DatasetCreate, svc: ReferenceDataService = Depends(_svc)
    ) -> DatasetModel:
        with _map_errors():
            return DatasetModel.model_validate(
                await svc.create_dataset(
                    name=body.name,
                    field_schema=body.field_schema,
                    key=body.key,
                    description=body.description,
                )
            )

    @r.get("/{key}", summary="Get a dataset", responses={404: {}})
    async def get_dataset(
        key: str, svc: ReferenceDataService = Depends(_svc)
    ) -> DatasetModel:
        with _map_errors():
            return DatasetModel.model_validate(await svc.get_dataset(key))

    @r.patch("/{key}", summary="Update a dataset", responses={404: {}})
    async def update_dataset(
        key: str, body: DatasetUpdate, svc: ReferenceDataService = Depends(_svc)
    ) -> DatasetModel:
        with _map_errors():
            return DatasetModel.model_validate(
                await svc.update_dataset(
                    key,
                    name=body.name,
                    description=body.description,
                    field_schema=body.field_schema,
                )
            )

    @r.delete("/{key}", summary="Soft-delete a dataset")
    async def delete_dataset(
        key: str, svc: ReferenceDataService = Depends(_svc)
    ) -> DeleteResult:
        return DeleteResult(deleted=await svc.delete_datasets([key]))

    @r.get(
        "/{key}/records",
        summary="Query records (equality filters as query params + search)",
        responses={400: {}, 404: {}},
    )
    async def query_records(
        key: str,
        request: Request,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        svc: ReferenceDataService = Depends(_svc),
    ) -> RecordListPageModel:
        filters = {
            k: v for k, v in request.query_params.items() if k not in _RESERVED_QUERY
        }
        with _map_errors():
            return RecordListPageModel.model_validate(
                await svc.query(
                    key, filters=filters, search=search, limit=limit, offset=offset
                )
            )

    @r.put("/{key}/records", summary="Upsert one record", responses={404: {}, 422: {}})
    async def upsert_record(
        key: str, body: RecordUpsert, svc: ReferenceDataService = Depends(_svc)
    ) -> RecordModel:
        with _map_errors():
            return RecordModel.model_validate(
                await svc.upsert_record(key, data=body.data, key=body.key)
            )

    @r.post(
        "/{key}/records/bulk",
        summary="Bulk upsert records",
        responses={404: {}, 422: {}},
    )
    async def bulk_upsert(
        key: str,
        body: BulkUpsert = Body(...),
        svc: ReferenceDataService = Depends(_svc),
    ) -> DeleteResult:
        with _map_errors():
            n = await svc.bulk_upsert(key, [rec.model_dump() for rec in body.records])
        return DeleteResult(deleted=n)

    @r.get("/{key}/records/{record_key}", summary="Get a record", responses={404: {}})
    async def get_record(
        key: str, record_key: str, svc: ReferenceDataService = Depends(_svc)
    ) -> RecordModel:
        with _map_errors():
            return RecordModel.model_validate(await svc.get_record(key, record_key))

    @r.delete(
        "/{key}/records/{record_key}",
        summary="Soft-delete a record",
        responses={404: {}},
    )
    async def delete_record(
        key: str, record_key: str, svc: ReferenceDataService = Depends(_svc)
    ) -> DeleteResult:
        with _map_errors():
            return DeleteResult(deleted=await svc.delete_records(key, [record_key]))

    return r


# endregion
