"""Tool: the dossier under audit + its expected document types.

Service-backed (factory). Bound to the run's ``dossier_key``; returns the
dossier's required ``document_def``s and what to ``look_for`` in each — the
agent's "what SHOULD be here" for the completeness (đủ) pass.
"""

from langchain_core.tools import StructuredTool, tool

from doci.userdata.documents import DocumentDefService
from doci.userdata.dossiers import DossierDefService
from doci.userdata.errors import NotFound


def build_get_dossier_spec(
    dossiers: DossierDefService, documents: DocumentDefService, dossier_key: str
) -> StructuredTool:
    async def get_dossier_spec() -> dict:
        """Get the dossier being audited and its expected document types (each with
        a 'look_for' note). Use this to know which documents must be present."""
        try:
            d = await dossiers.get_dossier(dossier_key)
        except NotFound:
            return {"ok": False, "error": f"dossier {dossier_key!r} not found."}
        docs = await documents.list_documents(dossier_key)
        return {
            "ok": True,
            "dossier": {"key": d.key, "name": d.name, "description": d.description},
            "documents": [
                {
                    "key": x.key,
                    "name": x.name,
                    "description": x.description,
                    "look_for": x.look_for,
                }
                for x in docs
            ],
        }

    return tool(get_dossier_spec)
