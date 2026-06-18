"""Dossier definitions: named case-file types with a plaintext description."""

from doci.userdata.dossiers.models import Dossier
from doci.userdata.dossiers.router import DossierModel, build_dossiers_router
from doci.userdata.dossiers.service import DossierService

__all__ = [
    "Dossier",
    "DossierService",
    "DossierModel",
    "build_dossiers_router",
]
