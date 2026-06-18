"""Tool: validate a tax code's length (§3.2).

Locale policy is a parameter: ``valid_lengths`` defaults to ``[10, 13]`` (Vietnam —
a 10-digit code, or a 10-digit parent + 3-digit branch), overridable per locale.
Format-only — a wrong length is reported as ``valid: false`` with a reason (not an
error); the tool never raises.
"""

import re

from langchain_core.tools import tool


def validate_tax_id(tax_code: str, valid_lengths: list[int] | None = None) -> dict:
    """Validate a tax code's digit length against ``valid_lengths`` (default VN [10,13]).

    Returns ``{"ok": True, "valid": bool, "normalized", "length", "reason"}``.
    Empty input returns ``{"ok": False, "error": ...}``.
    """
    if tax_code is None or not str(tax_code).strip():
        return {"ok": False, "error": "no tax code provided; pass the tax code string."}
    lengths = valid_lengths or [10, 13]
    digits = re.sub(r"\D", "", str(tax_code))
    valid = len(digits) in lengths
    return {
        "ok": True,
        "valid": valid,
        "normalized": digits,
        "length": len(digits),
        "reason": None
        if valid
        else f"tax code has {len(digits)} digits; expected one of {lengths}.",
    }


validate_tax_id_tool = tool(validate_tax_id)
