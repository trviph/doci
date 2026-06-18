"""Agent tools — one tool per module.

Each file exposes its callable plus a LangChain tool object (``<name>_tool``).
Pure deterministic checks (parse/compare/dates/tax/vat) take no dependencies;
service-backed tools export a ``build_<name>(...)`` factory. Tools never raise —
on bad input they return ``{"ok": False, "error": <how to fix>}`` so the agent
can correct its arguments and retry rather than crash the run.
"""
