"""Regression: CPU-bound PyMuPDF activities must offload off the event loop.

The PDF page fan-out (``process_node``) runs pages concurrently with a semaphore,
but that only buys real parallelism if each page's CPU work (PyMuPDF open / layout
/ rasterize) runs in a worker thread rather than blocking the single event-loop
thread. Each test fires N concurrent ``__call__``s whose *sync* body sleeps; if the
work is offloaded the wall-clock stays ~one sleep, if it blocks the loop it grows to
~N sleeps. Pure-unit (no DB, no real PDFs) — the blocking body is monkeypatched.
"""

import asyncio
import time

from doci.activities.create_thumb_image import CreateThumbImage
from doci.activities.create_thumb_pdf import CreateThumbPdf
from doci.activities.extract_content_pdf import ExtractContentPdf
from doci.activities.render_image_pdf import RenderImagePdf
from doci.activities.split_pdf import PdfPage, SplitPdf

_SLEEP = 0.2  # per-call blocking time in the (patched) sync body
_N = 5  # concurrent calls; serial would take ~_N * _SLEEP


def _run(coro):
    return asyncio.run(coro)


def _assert_parallel(elapsed: float, label: str) -> None:
    # Serial (loop-blocking) ~= _N * _SLEEP; parallel (offloaded) ~= _SLEEP.
    # Half the serial time is a wide, flake-proof margin between the two.
    assert elapsed < (_N * _SLEEP) / 2, (
        f"{label}: {elapsed:.3f}s for {_N}x{_SLEEP}s — sync body blocked the loop "
        "(work was not offloaded to a thread)"
    )


def _slow_render(_data: bytes) -> bytes:
    time.sleep(_SLEEP)
    return b"png-bytes"


def _offload_case(act, monkeypatch, attr: str, slow, label: str) -> None:
    monkeypatch.setattr(act, attr, slow, raising=False)

    async def scenario():
        start = time.perf_counter()
        out = await asyncio.gather(*(act(b"x") for _ in range(_N)))
        return out, time.perf_counter() - start

    out, elapsed = _run(scenario())
    assert all(r == b"png-bytes" for r in out)
    _assert_parallel(elapsed, label)


def test_render_image_pdf_offloads(monkeypatch):
    _offload_case(RenderImagePdf(), monkeypatch, "_render", _slow_render, "render_image_pdf")


def test_create_thumb_pdf_offloads(monkeypatch):
    _offload_case(CreateThumbPdf(), monkeypatch, "_render", _slow_render, "create_thumb_pdf")


def test_create_thumb_image_offloads(monkeypatch):
    _offload_case(
        CreateThumbImage(), monkeypatch, "_render", _slow_render, "create_thumb_image"
    )


def test_extract_content_pdf_offloads(monkeypatch):
    import doci.activities.extract_content_pdf as m

    act = ExtractContentPdf()

    class _Dummy:
        def close(self) -> None:
            pass

    def _slow_to_markdown(_doc, show_progress=False) -> str:
        time.sleep(_SLEEP)
        return "md"

    monkeypatch.setattr(m.pymupdf, "open", lambda **_k: _Dummy())
    monkeypatch.setattr(m.pymupdf4llm, "to_markdown", _slow_to_markdown)

    async def scenario():
        start = time.perf_counter()
        out = await asyncio.gather(*(act(b"x") for _ in range(_N)))
        return out, time.perf_counter() - start

    out, elapsed = _run(scenario())
    assert all(r == "md" for r in out)
    _assert_parallel(elapsed, "extract_content_pdf")


def test_split_pdf_offloads(monkeypatch):
    act = SplitPdf()

    def _slow_iter(_data: bytes):
        time.sleep(_SLEEP)
        yield PdfPage(
            page_number=1,
            page_count=1,
            content=b"p",
            text_len=0,
            image_count=0,
            has_annotations=False,
        )

    monkeypatch.setattr(act, "_iter_pages", _slow_iter)

    async def _consume():
        return [p async for p in act(b"x")]

    async def scenario():
        start = time.perf_counter()
        runs = await asyncio.gather(*(_consume() for _ in range(_N)))
        return runs, time.perf_counter() - start

    runs, elapsed = _run(scenario())
    assert all(len(pages) == 1 for pages in runs)
    _assert_parallel(elapsed, "split_pdf")
