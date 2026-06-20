"""Tool: read a knowledge entry's full body by key.

Service-backed (factory). The agent reads and reasons over the prose (the policy
lives here, not in code) — e.g. the LOA matrix or the threshold table.
"""

from langchain_core.tools import StructuredTool, tool

from doci.userdata.errors import NotFound
from doci.userdata.knowledge import KnowledgeService


def build_get_knowledge(knowledge: KnowledgeService) -> StructuredTool:
    async def get_knowledge(key: str) -> dict:
        """Get one knowledge entry's full markdown body by key (from search_knowledge).
        Next: use this body's content (thresholds, matrix, policy) to evaluate the
        rule and cite it in the finding's evidence."""
        try:
            k = await knowledge.get_knowledge(key)
        except NotFound:
            return {"ok": False, "error": f"knowledge {key!r} not found."}
        return {
            "ok": True,
            "key": k.key,
            "name": k.name,
            "description": k.description,
            "body": k.body,
            "next": (
                "Use this body's content (thresholds, matrix, policy) to evaluate "
                "the rule and cite it in the finding's evidence."
            ),
        }

    return tool(get_knowledge)
