"""Activity: extract a PDF's text-layer content as Markdown.

Uses ``pymupdf4llm`` (the PyMuPDF project's mupdf-based extractor, with its
in-process ML layout) to render the document as GitHub-flavored Markdown —
headings, lists, tables, code — rather than flat text. Expects a page with an
extractable text layer; image/scanned pages are rendered to an image and handled
by ``extract_content_image`` (vision LLM) instead.
"""

import asyncio

import pymupdf
import pymupdf4llm
from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span


@traced
class ExtractContentPdf:
    """Extract a PDF (bytes) into a single Markdown string from its text layer."""

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> str:
        """Return the document's text as Markdown."""
        # to_markdown runs an in-process ML layout pass (seconds/page, CPU-bound)
        # — offload so it doesn't block the event loop and serialize the page
        # fan-out. See ObjStore for the same pattern.
        return await asyncio.to_thread(self._to_markdown, data)

    def _to_markdown(self, data: bytes) -> str:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            return pymupdf4llm.to_markdown(doc, show_progress=False)
        finally:
            doc.close()
