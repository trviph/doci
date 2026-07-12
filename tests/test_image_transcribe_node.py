"""The image transcribe node: one download, extract ∥ annotate, both refs saved.

Replaces the old serial ``extract → annotate`` wiring (each node downloading the
blob independently). The two LLM passes are independent and now run concurrently
off a single shared download. Pure-unit — activities are fakes.
"""

import asyncio
import time
from uuid import uuid4

from doci.workflows.langgraph_document_mining_image.nodes.transcribe import (
    make_transcribe_node,
)

_LLM = 0.2  # simulated latency of each (independent) LLM pass


class _Annotation:
    def model_dump_json(self) -> str:
        return "{}"


def _build():
    state = {
        "stats": {"download": 0},
        "reflect_seen": [],
    }

    async def download(_media_id):
        state["stats"]["download"] += 1
        return b"image-bytes"

    async def extract(_data):
        await asyncio.sleep(_LLM)
        return "markdown"

    async def annotate(_data, dossier=None, reflect=False):
        state["reflect_seen"].append(reflect)
        await asyncio.sleep(_LLM)
        return _Annotation()

    saved: list[tuple[str, str]] = []

    async def save(_eid, _pid, kind, payload):
        saved.append((kind, payload))
        return f"ref:{kind}"

    node = make_transcribe_node(download, extract, annotate, save)
    return node, state, saved


def test_transcribe_downloads_once_saves_both_refs():
    node, stats, saved = _build()
    out = asyncio.run(
        node(
            {
                "media_id": uuid4(),
                "part_id": uuid4(),
                "execution_id": uuid4(),
                "dossier_spec": None,
            }
        )
    )
    assert stats["stats"]["download"] == 1, "blob must be downloaded exactly once"
    assert out == {
        "extract_ref": "ref:extract.md",
        "annotation_ref": "ref:annotation.json",
    }
    assert {kind for kind, _ in saved} == {"extract.md", "annotation.json"}


def test_transcribe_threads_annotate_reflect_flag():
    node, stats, _saved = _build()
    asyncio.run(
        node(
            {
                "media_id": uuid4(),
                "part_id": uuid4(),
                "execution_id": uuid4(),
                "dossier_spec": None,
                "annotate_reflect": True,
            }
        )
    )
    assert stats["reflect_seen"] == [True], "per-run reflect flag must reach annotate"


def test_transcribe_defaults_reflect_off_when_absent():
    node, stats, _saved = _build()
    asyncio.run(
        node(
            {
                "media_id": uuid4(),
                "part_id": uuid4(),
                "execution_id": uuid4(),
                "dossier_spec": None,
            }
        )
    )
    assert stats["reflect_seen"] == [False], "reflect defaults off when unset"


def test_transcribe_runs_extract_and_annotate_in_parallel():
    node, _stats, _saved = _build()

    async def scenario():
        start = time.perf_counter()
        await node(
            {
                "media_id": uuid4(),
                "part_id": uuid4(),
                "execution_id": uuid4(),
                "dossier_spec": None,
            }
        )
        return time.perf_counter() - start

    elapsed = asyncio.run(scenario())
    # Serial would be ~2 * _LLM; parallel ~ _LLM. Midpoint is a wide margin.
    assert elapsed < 1.5 * _LLM, (
        f"{elapsed:.3f}s — extract and annotate did not run concurrently"
    )
