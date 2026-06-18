"""Tool: parse a money string into a number.

Facts arrive as strings ("27,540,000 VNĐ", "1.200.000đ"); deterministic checks
need numbers. Tools never raise — on unparseable input they return
``{"ok": False, "error": ...}`` so the agent can fix its argument and retry.
"""

import re

from langchain_core.tools import tool


def to_money(value: object) -> float | None:
    """Best-effort parse of a VN-formatted money value to ``float`` (or ``None``).

    Handles thousands separators (``.`` or ``,``) and a decimal separator,
    inferring which is which; strips currency words/symbols.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    neg = raw.startswith("-") or raw.startswith("(")
    s = re.sub(r"[^0-9.,]", "", raw)
    if not s:
        return None
    if "," in s and "." in s:  # both present → the rightmost is the decimal sep
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 1 and len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")  # thousands grouping
        else:
            s = s.replace(",", ".")  # decimal comma
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 1 and len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")  # thousands grouping
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def parse_money(value: str) -> dict:
    """Parse a money string (e.g. "27,540,000 VNĐ") into a number.

    Returns ``{"ok": True, "value": <float>}`` or, when it cannot parse,
    ``{"ok": False, "error": <how to fix>}`` — do not treat a parse failure as a
    rule violation; re-read the fact and pass the numeric portion.
    """
    n = to_money(value)
    if n is None:
        return {
            "ok": False,
            "error": (
                f"could not parse {value!r} as money. Pass the numeric amount, e.g. "
                "27540000 or '27,540,000 VNĐ'."
            ),
        }
    return {"ok": True, "value": n}


parse_money_tool = tool(parse_money)
