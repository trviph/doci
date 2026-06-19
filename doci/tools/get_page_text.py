"""Tool: the extracted text (OCR/markdown) of one page.

Service-backed (factory). Bound to the mining ``execution_id``; a primary source
alongside the structured facts — the page's full transcription (including
``<signature>`` tokens) for when the agent needs exact wording or detail the
distilled facts don't capture.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.results import ResultKind, WorkflowResultService


def build_get_page_text(
    results: WorkflowResultService, execution_id: UUID
) -> StructuredTool:
    async def get_page_text(part_id: str) -> dict:
        """Get one page's full transcribed text (markdown, including `<signature>`
        tokens) by part_id — read it when you need exact wording or detail the
        distilled facts don't capture."""
        try:
            pid = UUID(part_id)
        except ValueError, TypeError:
            return {"ok": False, "error": f"{part_id!r} is not a valid part_id (UUID)."}
        row = await results.get(execution_id, pid, ResultKind.EXTRACT)
        if row is None:
            return {"ok": False, "error": f"no extracted text for part {part_id}."}
        return {"ok": True, "part_id": part_id, "text": row.content.get("result", "")}

    return tool(get_page_text)
