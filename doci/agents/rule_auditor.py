"""The rule-auditor subagent: evaluates ONE audit rule over the mined dossier.

A deepagents :class:`SubAgent` spec. The orchestrator delegates each applicable
rule to a fresh instance (via the ``task`` tool), passing the rule text; the
subagent gathers the facts the rule needs, runs the deterministic checks, and
records its findings — keeping each rule's reasoning in its own small context.
"""

from collections.abc import Mapping, Sequence

from deepagents import SubAgent
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools.base import BaseTool

from doci.prompts import load, output_language_directive
from doci.tools.find_tools import build_find_tools
from doci.tools.registry import ToolRegistry


def build_rule_auditor(
    base_tools: Sequence[BaseTool],
    tags: Mapping[str, Sequence[str]],
    model: BaseChatModel | str,
    language: str = "English",
    middleware: Sequence[AgentMiddleware] = (),
) -> SubAgent:
    """Build the rule-auditor subagent over ``base_tools`` (+ its own find_tools).

    ``middleware`` is attached to the subagent's own stack — the rule_auditor runs
    as a separately-compiled agent, so parent middleware (e.g. the LLM rate limiter)
    must be passed in here to cover its model calls too.
    """
    registry = ToolRegistry().add((t, tags.get(t.name, ())) for t in base_tools)
    tools: list[BaseTool] = [*base_tools, build_find_tools(registry)]
    return SubAgent(
        name="rule_auditor",
        description=(
            "Evaluate ONE audit rule against the dossier's mined facts: gather the "
            "facts the rule needs, run the deterministic checks, and record findings "
            "(pass / fail / needs_review) with evidence. Delegate one rule at a time."
        ),
        system_prompt=load("rule_auditor") + output_language_directive(language),
        tools=tools,
        model=model,
        middleware=list(middleware),
    )
