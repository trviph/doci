"""Document definitions: the documents expected within a dossier (m‑1)."""

from doci.userdata.documents.models import DocumentDef
from doci.userdata.documents.router import (
    DocumentModel,
    build_document_defs_router,
)
from doci.userdata.documents.service import DocumentDefService

__all__ = [
    "DocumentDef",
    "DocumentDefService",
    "DocumentModel",
    "build_document_defs_router",
]
