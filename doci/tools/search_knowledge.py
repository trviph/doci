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
        match; call get_knowledge(key) for the full body."""
        page = await knowledge.list_knowledge(search=query, limit=limit)
        return {
            "ok": True,
            "results": [
                {"key": k.key, "name": k.name, "description": k.description}
                for k in page.items
            ],
        }

    return tool(search_knowledge)
