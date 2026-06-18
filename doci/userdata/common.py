"""Shared helpers for the per-concern user data modules.

``gen_key`` derives a stable slug from a display name; ``ListPage`` is the
generic pagination container; ``_page_bounds`` clamps a (limit, offset) pair.

These are intentionally self-contained (a copy of the helpers in the legacy flat
``userdata.models``) so the new ``dossiers`` / ``documents`` / ``rules`` modules
don't depend on code slated for deletion at cutover.
"""

import re
import secrets
import string
from dataclasses import dataclass
from typing import Any

# region key derivation -------------------------------------------------------

_KEY_ALPHABET = string.ascii_lowercase + string.digits
_KEY_MAX_SEGMENTS = 5
_KEY_SUFFIX_LEN = 6


def gen_key(name: str) -> str:
    """Derive a slug key from a display name.

    Lowercase, alphanumeric runs hyphen-joined, capped at 5 segments, with a
    random 6-char suffix so two same-named entities don't collide:

    - ``"THE ORIGINAL PAYMENT"``                 → ``"the-original-payment-xqs2y6"``
    - ``"THIS IS SO FIRE! I LOVE IT SO MUCH <3"`` → ``"this-is-so-fire-i-zsw213"``
    """
    words = re.findall(r"[a-z0-9]+", name.lower())[:_KEY_MAX_SEGMENTS]
    suffix = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_SUFFIX_LEN))
    stem = "-".join(words)
    return f"{stem}-{suffix}" if stem else suffix


# endregion

# region pagination -----------------------------------------------------------

_DEFAULT_PAGE = 50
_MAX_PAGE = 200


@dataclass(frozen=True, slots=True)
class ListPage:
    """A page of records (newest first). ``items`` is typed by the caller."""

    items: list[Any]
    limit: int
    offset: int
    has_more: bool


def _page_bounds(limit: int | None, offset: int) -> tuple[int, int]:
    """Clamp ``(limit, offset)`` to sane bounds (default 50, max 200)."""
    return max(1, min(limit or _DEFAULT_PAGE, _MAX_PAGE)), max(0, offset)


# endregion
