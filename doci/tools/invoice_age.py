"""Tool: check an invoice's age and whether it is future-dated (§3.3/§4).

Flags invoices older than ``max_days`` (default 180) or dated in the future
relative to ``ref_date`` (default today). Tools never raise — an unparseable
date returns ``{"ok": False, "error": ...}``.
"""

from datetime import date

from langchain_core.tools import tool

from doci.tools.parse_date import to_date


def invoice_age(
    invoice_date: str, ref_date: str | None = None, max_days: int = 180
) -> dict:
    """Return the invoice's age in days plus ``future_dated`` / ``over_max`` flags.

    ``ref_date`` defaults to today. On a parse failure returns
    ``{"ok": False, "error": ...}`` — re-read the invoice date and retry.
    """
    inv = to_date(invoice_date)
    if inv is None:
        return {
            "ok": False,
            "error": f"could not parse invoice_date {invoice_date!r}; "
            "pass a date like '12 tháng 01 năm 2026' or '2026-01-12'.",
        }
    ref = to_date(ref_date) if ref_date else date.today().isoformat()
    if ref is None:
        return {"ok": False, "error": f"could not parse ref_date {ref_date!r}."}
    age = (date.fromisoformat(ref) - date.fromisoformat(inv)).days
    return {
        "ok": True,
        "invoice_date": inv,
        "ref_date": ref,
        "age_days": age,
        "future_dated": age < 0,
        "over_max": age > max_days,
        "max_days": max_days,
    }


invoice_age_tool = tool(invoice_age)
