"""User data layer: user/org-provided reference data for mining + audit.

Three concerns, two shapes:

- first-class **document groups** (:class:`DocumentGroupService`) and **audit
  rules** (:class:`AuditRuleService`);
- a unified **reference-dataset registry** (:class:`ReferenceDataService`) with
  one discover + query interface over arbitrary org datasets.
"""

from doci.userdata.errors import (
    DuplicateKey,
    NotFound,
    SchemaViolation,
    UnknownField,
    UserDataError,
)
from doci.userdata.groups_service import DocumentGroupService
from doci.userdata.models import (
    AuditRule,
    CheckExpr,
    CheckPrompt,
    DatasetInfo,
    DocumentGroup,
    DocumentGroupItem,
    FieldDef,
    FieldType,
    ListPage,
    ReferenceDataset,
    ReferenceRecord,
    Selector,
    Severity,
    gen_key,
)
from doci.userdata.refdata_service import ReferenceDataService
from doci.userdata.router import build_userdata_router
from doci.userdata.rules_service import AuditRuleService

__all__ = [
    "DocumentGroupService",
    "AuditRuleService",
    "ReferenceDataService",
    "build_userdata_router",
    # models
    "DocumentGroup",
    "DocumentGroupItem",
    "AuditRule",
    "CheckPrompt",
    "CheckExpr",
    "Selector",
    "Severity",
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
