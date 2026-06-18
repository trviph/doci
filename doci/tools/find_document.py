"""Tool: is a given document type present in the dossier? (completeness probe)

Service-backed (factory). Bound to the mining ``execution_id``; reports which
pages (if any) were classified as ``item_key`` — the đủ-pass check for whether a
required document is present.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.results import WorkflowResultService


def build_find_document(
    results: WorkflowResultService, execution_id: UUID
) -> StructuredTool:
    async def find_document(item_key: str) -> dict:
        """Check whether the dossier contains a page classified as document type
        `item_key`. Returns present + the matching page numbers."""
        pages = await results.page_index(execution_id)
        matched = [p for p in pages if p.item_key == item_key]
        return {
            "ok": True,
            "item_key": item_key,
            "present": bool(matched),
            "page_numbers": [p.page_number for p in matched],
        }

    return tool(find_document)
