"""Tool: the agent rules that apply to the dossier under audit.

Service-backed (factory). Bound to the run's ``dossier_key``; returns each rule's
prose markdown body — the checks the agent must evaluate.
"""

from langchain_core.tools import StructuredTool, tool

from doci.userdata.rules import AgentRuleService


def build_list_rules(rules: AgentRuleService, dossier_key: str) -> StructuredTool:
    async def list_rules() -> dict:
        """List the audit rules (markdown) that apply to this dossier."""
        try:
            applicable = await rules.rules_for_dossier(dossier_key)
        except Exception as exc:  # never raise out of a tool
            return {"ok": False, "error": f"could not load rules: {exc}"}
        return {
            "ok": True,
            "rules": [{"key": r.key, "name": r.name, "body": r.body} for r in applicable],
        }

    return tool(list_rules)
