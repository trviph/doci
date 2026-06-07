"""Persist a workflow result.

FIXME: this writes results to disk as a placeholder. Replace with real database
persistence (a results table keyed by media id + kind) once the schema lands.
"""

import os
import tempfile
from pathlib import Path
from uuid import UUID

_DEFAULT_DIR = Path(tempfile.gettempdir()) / "doci-results"


def _results_dir() -> Path:
    return Path(os.getenv("DOCI_RESULTS_DIR", str(_DEFAULT_DIR)))


def save_result(media_id: UUID, kind: str, payload: str) -> str:
    """Write ``payload`` for ``media_id``/``kind`` to disk; return the file path.

    FIXME: persist to the database instead of disk.
    """
    out_dir = _results_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{media_id}.{kind}"
    path.write_text(payload, encoding="utf-8")
    return str(path)
