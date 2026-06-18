"""Tool: compare two money amounts within the allowed audit variance (§3.1).

Allowed deviation = the smaller of ``tol_pct`` percent (of the larger amount) and
``tol_abs`` absolute (default 1% or 100,000 VND). Tools never raise — an
unparseable amount returns ``{"ok": False, "error": ...}``.
"""

from langchain_core.tools import tool

from doci.tools.parse_money import to_money


def compare_amount(
    a: str, b: str, tol_pct: float = 1.0, tol_abs: float = 100_000.0
) -> dict:
    """Check whether two amounts match within tolerance (smaller of %/absolute).

    Returns ``{"ok": True, "match": bool, "a", "b", "diff", "allowed"}``; on a
    parse failure returns ``{"ok": False, "error": ...}`` — that is NOT a
    mismatch, fix the argument and retry.
    """
    na, nb = to_money(a), to_money(b)
    bad = [name for name, n in (("a", na), ("b", nb)) if n is None]
    if bad:
        return {
            "ok": False,
            "error": (
                f"could not parse amount(s) {bad} from a={a!r}, b={b!r}. "
                "Pass the numeric amounts (e.g. 27540000)."
            ),
        }
    diff = abs(na - nb)
    allowed = min(max(abs(na), abs(nb)) * tol_pct / 100.0, tol_abs)
    return {
        "ok": True,
        "a": na,
        "b": nb,
        "diff": diff,
        "allowed": allowed,
        "match": diff <= allowed,
    }


compare_amount_tool = tool(compare_amount)
