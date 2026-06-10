"""Documents — the document domain (originals, pages/regions, lifecycle).

Composes the pure blob primitives in :mod:`doci.media`. A ``document`` owns its
derived ``document_part`` regions, each keyed by a ``locator`` for idempotency.
"""

from doci.documents.models import (
    DocumentListPage,
    DocumentPartRecord,
    DocumentRecord,
    DocumentStatus,
    PartKind,
    UploadIntent,
    page_locator,
)
from doci.documents.router import build_documents_router
from doci.documents.service import (
    AlreadyFinalized,
    DocumentError,
    DocumentNotFound,
    DocumentService,
)

__all__ = [
    "DocumentService",
    "DocumentRecord",
    "DocumentPartRecord",
    "DocumentListPage",
    "DocumentStatus",
    "PartKind",
    "UploadIntent",
    "page_locator",
    "DocumentError",
    "DocumentNotFound",
    "AlreadyFinalized",
    "build_documents_router",
]
