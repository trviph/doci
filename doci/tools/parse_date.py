"""Tool: parse a date string into ISO ``YYYY-MM-DD``.

Handles VN forms ("ngày 12 tháng 01 năm 2026"), ``dd/mm/yyyy`` / ``dd-mm-yyyy``,
and ISO ``yyyy-mm-dd``. Tools never raise — unparseable input returns
``{"ok": False, "error": ...}`` guiding the agent to fix its argument.
"""

import re
from datetime import date

from langchain_core.tools import tool


def _mk(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def to_date(value: object) -> str | None:
    """Best-effort parse of a date value to an ISO ``YYYY-MM-DD`` string (or ``None``)."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip().lower()
    if not s:
        return None
    # VN: "[ngày] 12 tháng 01 năm 2026"
    m = re.search(r"(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", s)
    if m:
        return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    # ISO first (4-digit year leading): yyyy-mm-dd
    m = re.search(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", s)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # VN numeric: dd/mm/yyyy or dd-mm-yyyy
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", s)
    if m:
        return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def parse_date(value: str) -> dict:
    """Parse a date string into ISO ``YYYY-MM-DD``.

    Returns ``{"ok": True, "date": "2026-01-12"}`` or, when it cannot parse,
    ``{"ok": False, "error": <how to fix>}`` — re-read the fact's date and pass
    it in a recognizable form (VN "dd tháng mm năm yyyy", dd/mm/yyyy, or ISO).
    """
    iso = to_date(value)
    if iso is None:
        return {
            "ok": False,
            "error": (
                f"could not parse {value!r} as a date. Pass a date like "
                "'12 tháng 01 năm 2026', '12/01/2026', or '2026-01-12'."
            ),
        }
    return {"ok": True, "date": iso}


parse_date_tool = tool(parse_date)
