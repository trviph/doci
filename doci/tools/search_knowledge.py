"""Tool: search the org knowledge base (reference material).

Service-backed (factory). Fuzzy search over name/description/body, ranked by
trigram similarity (best match first) so a multi-word or differently-phrased query
still surfaces the right entry; returns matches WITHOUT the full body (call
``get_knowledge`` for that) so the agent can pick what it needs — LOA matrix,
thresholds, VAT/PIT rules, vendor lists.
"""

from langchain_core.tools import StructuredTool, tool

from doci.userdata.knowledge import KnowledgeService


def build_search_knowledge(knowledge: KnowledgeService) -> StructuredTool:
    async def search_knowledge(query: str, limit: int = 10) -> dict:
        """Search the knowledge base for reference material (thresholds, LOA matrix,
        VAT rules, vendor policy, ...). Returns key + name + description for each
        match — these are previews, not the content.
        Next: call get_knowledge(key) to read an entry's full body."""
        page = await knowledge.list_knowledge(search=query, limit=limit)
        results = [
            {"key": k.key, "name": k.name, "description": k.description}
            for k in page.items
        ]
        keys = [r["key"] for r in results]
        next_hint = (
            f"Call get_knowledge(key) to read an entry's full body — keys: {keys}."
            if keys
            else "No matches; try other keywords."
        )
        return {"ok": True, "results": results, "next": next_hint}

    return tool(search_knowledge)
