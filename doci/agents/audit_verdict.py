"""The verdict agent: a small deepagents agent that concludes one audit.

Runs as a separate phase with a **fresh context** after the finding phase. It
reads only the recorded findings (+ the status criteria from the knowledge base)
and sets the dossier verdict — a small toolset and small context, so it's fast
and reliable where the monolithic single-phase agent timed out.
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
from doci.llm import build_chat_model
from doci.prompts import load, output_language_directive
from doci.tools.get_knowledge import build_get_knowledge
from doci.tools.list_findings import build_list_findings
from doci.tools.search_knowledge import build_search_knowledge
from doci.tools.set_verdict import build_set_verdict

if TYPE_CHECKING:
    from doci.bootstrap import Clients


def build_verdict_agent(
    *,
    clients: "Clients",
    audit_execution_id: UUID,
    dossier_key: str,
    document_id: UUID,
    language: str = "English",
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build the verdict agent for one audit run (reads findings, sets the verdict)."""
    model = model or build_chat_model(
        LLM_TASK,
        default_model=LLM_DEFAULT_MODEL,
        default_max_tokens=LLM_DEFAULT_MAX_TOKENS,
        # Same run as the finding phase — keep its turns on one cache node.
        cache_key=f"doci:verdict:{audit_execution_id}",
    )
    tools = [
        build_list_findings(clients.audit, audit_execution_id),
        build_search_knowledge(clients.userdata_knowledge),
        build_get_knowledge(clients.userdata_knowledge),
        build_set_verdict(clients.audit, audit_execution_id, dossier_key, document_id),
    ]
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=load("audit_verdict") + output_language_directive(language),
        checkpointer=checkpointer,
        name="audit_verdict",
    )
