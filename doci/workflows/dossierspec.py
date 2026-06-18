"""Resolve a workflow's optional ``dossier_key`` into a :class:`DossierSpec`.

The mining tasks call this once at start to turn the user-supplied dossier
``dossier_key`` into the small, serializable :class:`DossierSpec` dict threaded
through graph state to the annotate nodes. A missing/unknown key resolves to
``None`` (annotate falls back to generic, non-classifying behavior) rather than
failing the run.
"""

from typing import Any

from doci.activities.fields import DossierItemSpec, DossierSpec
from doci.userdata.documents import DocumentDefService
from doci.userdata.dossiers import DossierDefService
from doci.userdata.errors import NotFound


async def resolve_dossier_spec(
    dossiers: DossierDefService,
    documents: DocumentDefService,
    dossier_key: str | None,
) -> dict[str, Any] | None:
    """Fetch ``dossier_key`` and build a DossierSpec dict, or ``None`` if absent."""
    if not dossier_key:
        return None
    try:
        dossier = await dossiers.get_dossier(dossier_key)
    except NotFound:
        return None
    docs = await documents.list_documents(dossier_key)
    spec = DossierSpec(
        key=dossier.key,
        name=dossier.name,
        items=[
            DossierItemSpec(
                key=doc.key,
                name=doc.name,
                description=doc.description,
                look_for=doc.look_for,
            )
            for doc in docs
        ],
    )
    return spec.model_dump()
