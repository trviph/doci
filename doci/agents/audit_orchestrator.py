"""The audit finding agent: a deepagents deep agent that investigates one dossier.

Builds the orchestrator + the ``rule_auditor`` subagent over the run's tools
(bound to the mining/audit execution ids, dossier, and document). The
orchestrator runs the completeness pass and delegates the rules to the subagent
(its own judgement of how many rules per task), **recording findings only** — the
verdict is a separate phase. Tools come from the ``doci.tools`` factories; the LLM
decides which to use (it has ``find_tools``).
"""

from typing import TYPE_CHECKING
from uuid import UUID

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from doci.agents.rule_auditor import build_rule_auditor
from doci.llm import build_chat_model
from doci.prompts import load
from doci.tools.check_date_order import check_date_order_tool
from doci.tools.check_vat import check_vat_tool
from doci.tools.collect_facts import build_collect_facts
from doci.tools.compare_amount import compare_amount_tool
from doci.tools.find_document import build_find_document
from doci.tools.find_tools import build_find_tools
from doci.tools.fuzzy_match_name import fuzzy_match_name_tool
from doci.tools.get_dossier_spec import build_get_dossier_spec
from doci.tools.get_knowledge import build_get_knowledge
from doci.tools.get_page_annotation import build_get_page_annotation
from doci.tools.get_page_image import build_get_page_image
from doci.tools.get_page_text import build_get_page_text
from doci.tools.invoice_age import invoice_age_tool
from doci.tools.list_pages import build_list_pages
from doci.tools.list_rules import build_list_rules
from doci.tools.parse_date import parse_date_tool
from doci.tools.parse_money import parse_money_tool
from doci.tools.record_finding import build_record_finding
from doci.tools.registry import ToolRegistry
from doci.tools.search_knowledge import build_search_knowledge
from doci.tools.validate_tax_id import validate_tax_id_tool

if TYPE_CHECKING:
    from doci.bootstrap import Clients

LLM_TASK = "AUDIT"
# Orchestration + tool use is harder than annotation; default to a stronger model
# than the mining nano. Override via DOCI_LLM_AUDIT_MODEL.
LLM_DEFAULT_MODEL = "openai:gpt-5-mini-2025-08-07"
LLM_DEFAULT_MAX_TOKENS = 16000

# Discovery tags so find_tools ranks well even when a keyword isn't in the name.
_TAGS: dict[str, tuple[str, ...]] = {
    "parse_money": ("money", "amount", "number", "parse"),
    "parse_date": ("date", "parse"),
    "compare_amount": ("amount", "money", "compare", "match", "total"),
    "check_date_order": ("date", "order", "sequence", "chain", "chronology"),
    "fuzzy_match_name": ("name", "vendor", "supplier", "match", "fuzzy"),
    "validate_tax_id": ("tax", "code", "tin", "id"),
    "check_vat": ("vat", "tax", "rate", "invoice"),
    "invoice_age": ("invoice", "date", "age", "expiry"),
    "collect_facts": ("facts", "gather", "document", "fields"),
    "get_page_annotation": ("annotation", "facts", "page"),
    "get_page_text": ("text", "extract", "ocr", "page"),
    "get_page_image": ("image", "visual", "signature", "stamp", "look"),
    "list_pages": ("pages", "index", "classification", "item"),
    "find_document": ("document", "present", "coverage", "exists"),
    "search_knowledge": ("knowledge", "reference", "policy", "threshold", "matrix"),
    "get_knowledge": ("knowledge", "reference", "policy", "body"),
    "record_finding": ("finding", "record", "result"),
    "set_verdict": ("verdict", "conclude", "pass", "fail"),
    "get_dossier_spec": ("dossier", "required", "documents", "spec"),
    "list_rules": ("rules", "audit", "checks"),
}

_DETERMINISTIC = [
    parse_money_tool,
    parse_date_tool,
    compare_amount_tool,
    check_date_order_tool,
    fuzzy_match_name_tool,
    validate_tax_id_tool,
    check_vat_tool,
    invoice_age_tool,
]


def build_finding_agent(
    *,
    clients: "Clients",
    mining_execution_id: UUID,
    audit_execution_id: UUID,
    dossier_key: str,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build the finding (investigation) agent for one dossier run.

    ``mining_execution_id`` keys the mined results; ``audit_execution_id`` is the
    audit run findings hang off. Records findings only — the verdict is a separate
    phase (see :func:`doci.agents.audit_verdict.build_verdict_agent`).
    """
    model = model or build_chat_model(
        LLM_TASK,
        default_model=LLM_DEFAULT_MODEL,
        default_max_tokens=LLM_DEFAULT_MAX_TOKENS,
    )
    rds = clients.workflow_results

    # mined evidence (keyed to the mining run)
    list_pages = build_list_pages(rds, mining_execution_id)
    find_doc = build_find_document(rds, mining_execution_id)
    evidence = [
        list_pages,
        build_get_page_annotation(rds, mining_execution_id),
        build_get_page_text(rds, mining_execution_id),
        build_collect_facts(rds, mining_execution_id),
        find_doc,
        build_get_page_image(clients.media, clients.postgres),
    ]
    # reference knowledge
    search_kb = build_search_knowledge(clients.userdata_knowledge)
    get_kb = build_get_knowledge(clients.userdata_knowledge)
    # output (keyed to the audit run) — findings only; verdict is a separate phase
    record = build_record_finding(clients.audit, audit_execution_id)

    # rule subagent: evidence + deterministic + knowledge + record_finding
    sub_base = [*evidence, search_kb, get_kb, record, *_DETERMINISTIC]
    rule_sub = build_rule_auditor(sub_base, _TAGS, model)

    # orchestrator: requirements + coverage + knowledge + record
    orch_base = [
        build_get_dossier_spec(
            clients.userdata_dossier_defs, clients.userdata_document_defs, dossier_key
        ),
        build_list_rules(clients.userdata_agent_rules, dossier_key),
        list_pages,
        find_doc,
        search_kb,
        get_kb,
        record,
    ]
    registry = ToolRegistry().add((t, _TAGS.get(t.name, ())) for t in orch_base)
    orch_tools = [*orch_base, build_find_tools(registry)]

    return create_deep_agent(
        model=model,
        tools=orch_tools,
        system_prompt=load("audit_orchestrator"),
        subagents=[rule_sub],
        checkpointer=checkpointer,
        name="audit",
    )
