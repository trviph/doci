"""FastAPI router for the reference-data registry.

:func:`build_userdata_router` mounts the ``/reference-data`` sub-router, which
resolves its service from ``app.state.userdata_refdata`` when not explicitly
bound (mirroring the documents router). Domain errors map to HTTP codes via
:func:`_map_errors`.

(Dossier / document-def / agent-rule routers live in the per-concern submodules
``dossiers`` / ``documents`` / ``rules`` and are mounted separately.)
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from doci.userdata.errors import DuplicateKey, NotFound, SchemaViolation, UnknownField
from doci.userdata.models import FieldDef
from doci.userdata.refdata_service import ReferenceDataService

# region request / response models --------------------------------------------


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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


class UpsertResult(BaseModel):
    upserted: int


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
    *, refdata: ReferenceDataService | None = None
) -> APIRouter:
    """Build the user-data APIRouter (the reference-data sub-router)."""
    router = APIRouter(tags=["userdata"])
    router.include_router(_refdata_router(refdata))
    return router


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
    ) -> UpsertResult:
        with _map_errors():
            n = await svc.bulk_upsert(key, [rec.model_dump() for rec in body.records])
        return UpsertResult(upserted=n)

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
