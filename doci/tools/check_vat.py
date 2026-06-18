"""Tool: check a VAT amount against subtotal × rate (§4).

The arithmetic is locale-agnostic; the legal rate set is a parameter —
``allowed_rates`` defaults to ``[0, 5, 8, 10]`` (Vietnam), overridable per locale.
``rate`` is a percent (e.g. 10 or "10%"). VAT must equal subtotal × rate within
``tol_pct`` (default 0.5%). Tools never raise — unparseable money returns
``{"ok": False, "error": ...}``.
"""

import re

from langchain_core.tools import tool

from doci.tools.parse_money import to_money


def check_vat(
    subtotal: str,
    rate: str,
    vat: str,
    tol_pct: float = 0.5,
    allowed_rates: list[float] | None = None,
) -> dict:
    """Verify VAT = subtotal × rate within tolerance, and that the rate is allowed.

    Returns ``{"ok": True, "expected", "vat", "diff", "allowed", "match", "rate",
    "rate_valid"}``; on a parse failure returns ``{"ok": False, "error": ...}`` —
    fix the argument, do not treat it as a violation.
    """
    rates = (
        [0.0, 5.0, 8.0, 10.0]
        if allowed_rates is None
        else [float(r) for r in allowed_rates]
    )
    sub = to_money(subtotal)
    got = to_money(vat)
    try:
        rate_val = float(re.sub(r"[^0-9.]", "", str(rate)))
    except ValueError:
        rate_val = None
    bad = [
        n for n, v in (("subtotal", sub), ("vat", got), ("rate", rate_val)) if v is None
    ]
    if bad:
        return {
            "ok": False,
            "error": f"could not parse {bad} from subtotal={subtotal!r}, "
            f"rate={rate!r}, vat={vat!r}.",
        }
    expected = sub * rate_val / 100.0
    diff = abs(got - expected)
    allowed = max(expected, 1.0) * tol_pct / 100.0
    return {
        "ok": True,
        "expected": expected,
        "vat": got,
        "diff": diff,
        "allowed": allowed,
        "match": diff <= allowed,
        "rate": rate_val,
        "rate_valid": rate_val in rates,
    }


check_vat_tool = tool(check_vat)
