"""Tool: verify a labeled sequence of dates is non-decreasing (§3.3).

The canonical chain is PR ≤ PO ≤ GRN/BBNT ≤ Invoice ≤ Payment. Pass the dates in
the order they must occur; the tool reports any out-of-order pair. Unparseable
dates are reported (not fatal) so the agent can decide; the tool never raises.
"""

from langchain_core.tools import tool

from doci.tools.parse_date import to_date


def check_date_order(dates: list[dict]) -> dict:
    """Check that ``dates`` (``[{"label","date"}, ...]``) are in non-decreasing order.

    Returns ``{"ok": True, "ordered": bool, "parsed": [...], "unparsed": [...],
    "violations": [{"before","after"}]}``. ``ordered`` reflects only the dates
    that parsed; ``unparsed`` labels could not be read — gather better evidence
    or note them. Never a hard error on a single bad date.
    """
    parsed: list[dict] = []
    unparsed: list[str] = []
    for i, item in enumerate(dates or []):
        label = str(item.get("label", f"#{i}"))
        iso = to_date(item.get("date"))
        (parsed if iso else unparsed).append({"label": label, "date": iso} if iso else label)
    violations = []
    for prev, cur in zip(parsed, parsed[1:]):
        if cur["date"] < prev["date"]:
            violations.append({"before": prev, "after": cur})
    return {
        "ok": True,
        "ordered": not violations,
        "parsed": parsed,
        "unparsed": unparsed,
        "violations": violations,
        "note": None
        if len(parsed) >= 2
        else "fewer than 2 dates parsed; ordering not meaningfully checked",
    }


check_date_order_tool = tool(check_date_order)
