"""Dossier definitions: named case-file types with a plaintext description."""

from doci.userdata.dossiers.models import DossierDef
from doci.userdata.dossiers.router import DossierModel, build_dossiers_router
from doci.userdata.dossiers.service import DossierDefService

__all__ = [
    "DossierDef",
    "DossierDefService",
    "DossierModel",
    "build_dossiers_router",
]
