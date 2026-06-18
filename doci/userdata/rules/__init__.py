"""Agent rules: named markdown rules and their m‑n link to dossiers."""

from doci.userdata.rules.models import AgentRule
from doci.userdata.rules.router import RuleModel, build_agent_rules_router
from doci.userdata.rules.service import AgentRuleService

__all__ = [
    "AgentRule",
    "AgentRuleService",
    "RuleModel",
    "build_agent_rules_router",
]
