"""Tool: fuzzy-match two names (vendor name matching, §3.2 — threshold 85%).

Diacritic- and case-insensitive similarity (stdlib ``difflib``); returns a score
and whether it clears the threshold. Tools never raise — empty input returns an
``error`` telling the agent which side was missing.
"""

import re
import unicodedata
from difflib import SequenceMatcher

from langchain_core.tools import tool


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))  # drop diacritics
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str, b: str) -> float:
    """Normalized similarity 0–100 (diacritic/case-insensitive)."""
    return round(SequenceMatcher(None, _norm(a), _norm(b)).ratio() * 100, 1)


def fuzzy_match_name(a: str, b: str, threshold: float = 85.0) -> dict:
    """Compare two names; ``match`` = score ≥ ``threshold``.

    Returns ``{"ok": True, "score", "match", "threshold"}``; if a side is empty,
    ``{"ok": False, "error": ...}`` — supply both names from the documents.
    """
    if not (a and a.strip()) or not (b and b.strip()):
        return {
            "ok": False,
            "error": f"need two non-empty names; got a={a!r}, b={b!r}.",
        }
    score = similarity(a, b)
    return {"ok": True, "score": score, "match": score >= threshold, "threshold": threshold}


fuzzy_match_name_tool = tool(fuzzy_match_name)
