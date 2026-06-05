"""Activity: render a PDF page as a small, content-obfuscated PNG thumbnail.

Produces a tiny grayscale PNG for listings that hides the page's actual data:
- Text pages are "blockized" VSCode-minimap style — one gray rectangle per word,
  so layout shows but words are unreadable.
- Scanned/image pages (no extractable text) are rendered at very low resolution,
  a blur/mosaic that conveys the document's shape without legible content.
Returns the raw PNG bytes (store as a ``MediaType.THUMB`` derivative). First page
only (inputs are single post-split pages). PyMuPDF only — no Pillow.
"""

import pymupdf
from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span


@traced
class CreateThumbPdf:
    """Render a PDF's first page as a small, obfuscated minimap/mosaic PNG."""

    def __init__(
        self, *, width: int = 160, shade: float = 0.55, scan_width: int = 64
    ) -> None:
        self._width = max(1, width)  # minimap width (px) for text pages
        self._fill = (shade, shade, shade)  # block gray, 0=black .. 1=white
        self._scan_width = max(1, scan_width)  # low render width => blur/obfuscate

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> bytes:
        """Return a small, content-obfuscated PNG of the first page as bytes."""
        return self._render(data)

    def _render(self, data: bytes) -> bytes:
        src = pymupdf.open(stream=data, filetype="pdf")
        try:
            page = src[0]
            words = page.get_text("words")
            return self._minimap(page, words) if words else self._mosaic(page)
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

    def _mosaic(self, page: pymupdf.Page) -> bytes:
        # No text layer => scanned/image (or blank). Render at very low resolution
        # so content is blurred/illegible (obfuscated) while shape/tone survive.
        scale = self._scan_width / page.rect.width
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY
        )
        return pix.tobytes("png")
