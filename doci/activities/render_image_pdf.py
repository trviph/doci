"""Activity: render a PDF page to a full-resolution raster image (PNG).

Unlike ``create_thumb_pdf`` (a tiny, obfuscated minimap) this renders the page at
a legibility-oriented scale so a vision LLM can read it. Used for image/scanned
pages — the ones the text-layer ``extract_content_pdf`` path can't read: the page
is rasterized here, then handed to ``extract_content_image`` / ``annotate_image``
(which take image bytes, not PDF bytes). Expects a single-page PDF (a post-split
page); renders the first page. Returns the raw PNG bytes. PyMuPDF only — no Pillow.
"""

import pymupdf
from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span


@traced
class RenderImagePdf:
    """Render a PDF's first page to a full-resolution PNG for vision passes."""

    def __init__(self, *, zoom: float = 2.0) -> None:
        # Render scale (1.0 == 72 dpi); 2.0 ~= 144 dpi keeps text legible to a
        # vision model without ballooning the image.
        self._matrix = pymupdf.Matrix(zoom, zoom)

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> bytes:
        """Return the first page rendered as PNG bytes."""
        return self._render(data)

    def _render(self, data: bytes) -> bytes:
        src = pymupdf.open(stream=data, filetype="pdf")
        try:
            page = src[0]
            return page.get_pixmap(matrix=self._matrix).tobytes("png")
        finally:
            src.close()
