"""Activity: render a text-bearing PDF page as a small, obfuscated PNG thumbnail.

Produces a tiny grayscale PNG for listings that hides the page's actual data:
text is "blockized" VSCode-minimap style — one gray rectangle per word, so layout
shows but words are unreadable. Returns the raw PNG bytes (store as a
``MediaType.THUMB`` derivative). First page only (inputs are single post-split
pages). PyMuPDF only — no Pillow.

Expects a page with an extractable text layer; scanned/image pages (no text) are
rendered to an image and thumbnailed by ``create_thumb_image`` instead. A page
with no words yields a blank minimap by design — route scanned pages elsewhere.
"""

import asyncio

import pymupdf
from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span


@traced
class CreateThumbPdf:
    """Render a PDF's first page as a small, obfuscated minimap PNG."""

    def __init__(self, *, width: int = 160, shade: float = 0.55) -> None:
        self._width = max(1, width)  # minimap width (px) for text pages
        self._fill = (shade, shade, shade)  # block gray, 0=black .. 1=white

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> bytes:
        """Return a small, content-obfuscated PNG of the first page as bytes."""
        # CPU-bound layout + rasterization — offload so it doesn't block the
        # event loop (and serialize the page fan-out).
        return await asyncio.to_thread(self._render, data)

    def _render(self, data: bytes) -> bytes:
        src = pymupdf.open(stream=data, filetype="pdf")
        try:
            page = src[0]
            return self._minimap(page, page.get_text("words"))
        finally:
            src.close()

    def _minimap(self, page: pymupdf.Page, words: list) -> bytes:
        scale = self._width / page.rect.width
        out = pymupdf.open()
        try:
            thumb = out.new_page(
                width=self._width, height=max(1, round(page.rect.height * scale))
            )
            shape = thumb.new_shape()
            for x0, y0, x1, y1, *_ in words:
                shape.draw_rect(
                    pymupdf.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale)
                )
            shape.finish(fill=self._fill, color=None, width=0)
            shape.commit()
            return thumb.get_pixmap(colorspace=pymupdf.csGRAY).tobytes("png")
        finally:
            out.close()
