"""Tool: discover relevant tools by keyword (instead of binding them all).

Service-/registry-backed (factory). ``find_tools(['vat', 'tax'])`` ranks the run's
tool registry and returns the matching tools' name, description, and arguments so
the agent can pick what it needs. The agent graph binds the discovered tools on
demand. Never raises.
"""

from langchain_core.tools import StructuredTool, tool

from doci.tools.registry import ToolRegistry


def build_find_tools(registry: ToolRegistry) -> StructuredTool:
    def find_tools(keywords: list[str], limit: int = 8) -> dict:
        """Find tools relevant to what you need to do, by keyword (e.g.
        ['vat', 'tax'] or ['date', 'order']). Returns ranked tools with their
        name, description, and arguments — then call a returned tool by its name.
        Use this instead of guessing tool names."""
        if isinstance(keywords, str):  # tolerate a single string
            keywords = [keywords]
        results = registry.search(keywords or [], limit=limit)
        if not results:
            return {
                "ok": True,
                "results": [],
                "note": "no tools matched; try broader keywords or no keywords to list all.",
            }
        return {"ok": True, "results": results}

    return tool(find_tools)
