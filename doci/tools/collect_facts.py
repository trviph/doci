"""Tool: gather facts across all pages of a document type.

Service-backed (factory). Bound to the mining ``execution_id``; merges the
``facts`` from every page classified as ``item_key`` (e.g. all invoice facts) so
the agent can compare across documents without pulling each page.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.results import ResultKind, WorkflowResultService


def build_collect_facts(
    results: WorkflowResultService, execution_id: UUID
) -> StructuredTool:
    async def collect_facts(item_key: str) -> dict:
        """Collect the facts from every page classified as document type `item_key`
        (e.g. 'invoice', 'pr', 'po-epr'). Each fact keeps its page_number + source."""
        pages = await results.page_index(execution_id)
        matched = [p for p in pages if p.item_key == item_key]
        facts: list[dict] = []
        for p in matched:
            row = await results.get(execution_id, p.part_id, ResultKind.ANNOTATION)
            if row is None:
                continue
            for f in row.content.get("facts", []) or []:
                facts.append(
                    {**f, "page_number": p.page_number, "part_id": str(p.part_id)}
                )
        return {
            "ok": True,
            "item_key": item_key,
            "page_numbers": [p.page_number for p in matched],
            "facts": facts,
        }

    return tool(collect_facts)
