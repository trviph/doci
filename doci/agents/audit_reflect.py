"""The reflection agent: consolidates the recorded findings before the verdict.

Runs as a separate phase with a **fresh context** between the finding and verdict
phases. The finding phase fans out to multiple agents (the orchestrator's
completeness pass + N ``rule_auditor`` subagents), each recording findings
independently — so duplicates and contradictory findings accumulate. This agent
reads the recorded findings, and *surgically* reconciles them: it deletes exact
duplicates and, where two findings on the same rule/subject conflict, verifies
against the mined evidence and keeps the correct one. Correct findings are left
untouched. It does not set a verdict.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from doci.agents.audit_orchestrator import (
    LLM_DEFAULT_MAX_TOKENS,
    LLM_DEFAULT_MODEL,
    LLM_TASK,
)
from doci.agents.ratelimit import build_rate_limit_middleware
from doci.llm import build_chat_model
from doci.prompts import load, output_language_directive
from doci.tools.collect_facts import build_collect_facts
from doci.tools.delete_finding import build_delete_finding
from doci.tools.get_page_annotation import build_get_page_annotation
from doci.tools.get_page_image import build_get_page_image
from doci.tools.get_page_text import build_get_page_text
from doci.tools.list_findings import build_list_findings
from doci.tools.list_pages import build_list_pages
from doci.tools.record_finding import build_record_finding

if TYPE_CHECKING:
    from doci.bootstrap import Clients


def build_reflection_agent(
    *,
    clients: "Clients",
    mining_execution_id: UUID,
    audit_execution_id: UUID,
    language: str = "English",
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build the reflection agent for one audit run (dedups/reconciles findings).

    Reads the audit run's findings (``audit_execution_id``); grounds contradiction
    checks in the mined evidence (``mining_execution_id``); rewrites the finding
    set surgically (delete duplicates / the wrong side of a conflict, record a
    merged finding). Does not set a verdict.
    """
    model = model or build_chat_model(
        LLM_TASK,
        default_model=LLM_DEFAULT_MODEL,
        default_max_tokens=LLM_DEFAULT_MAX_TOKENS,
        # Same run as the finding/verdict phases — keep its turns on one cache node.
        cache_key=f"doci:reflect:{audit_execution_id}",
    )
    rds = clients.workflow_results
    tools = [
        # the finding set to consolidate (keyed to the audit run)
        build_list_findings(clients.audit, audit_execution_id),
        build_delete_finding(clients.audit, audit_execution_id),
        build_record_finding(clients.audit, audit_execution_id),
        # mined evidence to adjudicate contradictions (keyed to the mining run)
        build_list_pages(rds, mining_execution_id),
        build_get_page_annotation(rds, mining_execution_id),
        build_get_page_text(rds, mining_execution_id),
        build_collect_facts(rds, mining_execution_id),
        build_get_page_image(clients.media, clients.postgres),
    ]
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=load("audit_reflect") + output_language_directive(language),
        middleware=build_rate_limit_middleware(clients.kv, LLM_TASK),
        checkpointer=checkpointer,
        name="audit_reflect",
    )
