"""Tool: the full mined annotation of one page (facts + classification).

Service-backed (factory). Bound to the mining ``execution_id``; pulls the page's
``annotation.json`` content (category, description, ``item_key``, ``facts``).
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.results import ResultKind, WorkflowResultService


def build_get_page_annotation(
    results: WorkflowResultService, execution_id: UUID
) -> StructuredTool:
    async def get_page_annotation(part_id: str) -> dict:
        """Get one page's full annotation (facts with their source quotes) by part_id
        (from list_pages)."""
        try:
            pid = UUID(part_id)
        except ValueError, TypeError:
            return {"ok": False, "error": f"{part_id!r} is not a valid part_id (UUID)."}
        row = await results.get(execution_id, pid, ResultKind.ANNOTATION)
        if row is None:
            return {"ok": False, "error": f"no annotation for part {part_id}."}
        return {"ok": True, "part_id": part_id, "annotation": row.content}

    return tool(get_page_annotation)
