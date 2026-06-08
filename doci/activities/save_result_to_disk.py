"""Activity: persist a workflow result to local disk.

One of the ``save_result_to_*`` backends (a ``save_result_to_db`` / object-store
variant will join it later). Writes ``<execution_id>/<media_id>.<kind>`` under the
results directory — ``DOCI_RESULTS_DIR`` if set, else a temp dir — and returns the
path. Grouping by ``execution_id`` keeps a single run's results together. For
trusted, server-generated content (extracted Markdown, annotation JSON, ...).
"""

import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span

#: The shared save-result interface every ``save_result_to_*`` backend implements:
#: ``(execution_id, media_id, kind, payload) -> ref`` where ``ref`` locates the
#: stored result.
SaveResult = Callable[[UUID, UUID, str, str], Awaitable[str]]

_DEFAULT_DIR = Path(tempfile.gettempdir()) / "doci-results"


@traced
class SaveResultToDisk:
    """Persist a workflow result to local disk; returns the written file path."""

    def __init__(self, base_dir: Path | None = None) -> None:
        # When None, resolve DOCI_RESULTS_DIR at call time (falling back to a
        # temp dir), so the env var stays authoritative.
        self._base_dir = base_dir

    def _dir(self) -> Path:
        if self._base_dir is not None:
            return self._base_dir
        return Path(os.getenv("DOCI_RESULTS_DIR", str(_DEFAULT_DIR)))

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(
        self, execution_id: UUID, media_id: UUID, kind: str, payload: str
    ) -> str:
        """Write ``payload`` for an execution's ``media_id``/``kind``; return the path."""
        out_dir = self._dir() / str(execution_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{media_id}.{kind}"
        path.write_text(payload, encoding="utf-8")
        return str(path)
