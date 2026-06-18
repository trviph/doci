"""Tool: the mined page index of the document under audit.

Service-backed (factory). Bound to the mining ``execution_id``; returns each
page's part_id + classification (``item_key``) + category — the compact "table
of contents" the agent scans before pulling any full page.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.results import WorkflowResultService


def build_list_pages(results: WorkflowResultService, execution_id: UUID) -> StructuredTool:
    async def list_pages() -> dict:
        """List the mined pages: page_number, part_id, and the document type each
        was classified as (item_key). Start here, then pull specific pages."""
        pages = await results.page_index(execution_id)
        return {
            "ok": True,
            "pages": [
                {
                    "part_id": str(p.part_id),
                    "page_number": p.page_number,
                    "item_key": p.item_key,
                    "category": p.category,
                }
                for p in pages
            ],
        }

    return tool(list_pages)
