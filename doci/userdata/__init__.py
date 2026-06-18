"""User data layer.

- Per-concern definitions live in submodules: :mod:`dossiers`, :mod:`documents`,
  :mod:`rules` (dossier defs, document defs, agent rules).
- The unified **reference-dataset registry** (:class:`ReferenceDataService`)
  exposes one discover + query interface over arbitrary org datasets.
"""

from doci.userdata.errors import (
    DuplicateKey,
    NotFound,
    SchemaViolation,
    UnknownField,
    UserDataError,
)
from doci.userdata.models import (
    DatasetInfo,
    FieldDef,
    FieldType,
    ListPage,
    ReferenceDataset,
    ReferenceRecord,
    gen_key,
)
from doci.userdata.refdata_service import ReferenceDataService
from doci.userdata.router import build_userdata_router

__all__ = [
    "ReferenceDataService",
    "build_userdata_router",
    # models
    "ReferenceDataset",
    "ReferenceRecord",
    "DatasetInfo",
    "FieldDef",
    "FieldType",
    "ListPage",
    "gen_key",
    # errors
    "UserDataError",
    "NotFound",
    "DuplicateKey",
    "SchemaViolation",
    "UnknownField",
]
