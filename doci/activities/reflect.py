"""Env-level gate for the annotation reflection pass.

The reflect pass is gated by two flags: this env switch is the *ceiling* — when
off, the reflect model is never built (``deps.py`` passes ``reflect_model=None``)
so no per-run request can turn reflection on. When on, the per-run ``reflect``
flag on each ``annotate`` call decides whether it actually runs.
"""

import os

_TRUTHY = {"1", "true", "yes", "on"}


def annotate_reflect_enabled() -> bool:
    """Whether the annotation reflect pass is permitted (``DOCI_ANNOTATE_REFLECT``)."""
    return os.getenv("DOCI_ANNOTATE_REFLECT", "").strip().lower() in _TRUTHY
