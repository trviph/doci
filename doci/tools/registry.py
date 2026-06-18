"""A small in-memory tool registry for discovery + dynamic binding.

Holds the run's instantiated tools with optional tags; ``search`` ranks them by
keyword relevance over name/description/tags. The ``find_tools`` tool searches
this registry; the agent graph binds ``registry.tools(selected)`` on demand so
the model isn't handed every tool at once.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from langchain_core.tools.base import BaseTool


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A registered tool plus optional discovery tags."""

    tool: BaseTool
    tags: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description or ""


class ToolRegistry:
    """Name-keyed registry with keyword-relevance ``search``."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, tool: BaseTool, tags: Iterable[str] = ()) -> "ToolRegistry":
        self._specs[tool.name] = ToolSpec(tool, tuple(tags))
        return self

    def add(self, items: Iterable[tuple[BaseTool, Iterable[str]]]) -> "ToolRegistry":
        for tool, tags in items:
            self.register(tool, tags)
        return self

    def get(self, name: str) -> BaseTool | None:
        spec = self._specs.get(name)
        return spec.tool if spec else None

    def tools(self, names: Sequence[str]) -> list[BaseTool]:
        """The bindable tool objects for ``names`` (unknown names skipped)."""
        return [self._specs[n].tool for n in names if n in self._specs]

    def all_tools(self) -> list[BaseTool]:
        return [s.tool for s in self._specs.values()]

    def names(self) -> list[str]:
        return list(self._specs)

    def search(self, keywords: Sequence[str], limit: int = 8) -> list[dict]:
        """Rank tools by keyword relevance. No keywords → all tools (name order).

        Scoring per keyword: +3 name hit, +2 tag hit, +1 description hit.
        Returns ``[{name, description, args, score}]`` (highest first).
        """
        kws = [k.lower().strip() for k in keywords if k and k.strip()]
        scored: list[tuple[int, ToolSpec]] = []
        for spec in self._specs.values():
            name_l = spec.name.lower()
            desc_l = spec.description.lower()
            tags_l = [t.lower() for t in spec.tags]
            score = 0
            for kw in kws:
                if kw in name_l:
                    score += 3
                if any(kw in t for t in tags_l):
                    score += 2
                if kw in desc_l:
                    score += 1
            if score > 0 or not kws:
                scored.append((score, spec))
        scored.sort(key=lambda x: (-x[0], x[1].name))
        return [
            {
                "name": s.name,
                "description": s.description,
                "args": list(s.tool.args),
                "score": score,
            }
            for score, s in scored[:limit]
        ]
