"""Activity: render a raw image as a small, content-obfuscated PNG thumbnail.

Takes raw image bytes (PNG/JPEG/…) and renders them at very low resolution — a
blur/mosaic that conveys the image's shape and tone without legible content.
Returns the raw PNG bytes (store as a ``MediaType.THUMB`` derivative). The image
analog of ``create_thumb_pdf``'s minimap, and the thumbnail counterpart to the
source-agnostic ``extract_content_image`` / ``annotate_image``. PyMuPDF only —
no Pillow.
"""

import asyncio

import pymupdf
from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span


@traced
class CreateThumbImage:
    """Render a raw image as a small, obfuscated grayscale mosaic PNG."""

    def __init__(self, *, width: int = 64) -> None:
        self._width = max(1, width)  # low render width => blur/obfuscate

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> bytes:
        """Return a small, content-obfuscated PNG of the image as bytes."""
        # CPU-bound rasterization — offload so it doesn't block the event loop
        # (and serialize the page fan-out).
        return await asyncio.to_thread(self._render, data)

    def _render(self, data: bytes) -> bytes:
        # Render at very low resolution so content is blurred/illegible
        # (obfuscated) while shape/tone survive. PyMuPDF opens a raster image as
        # a single-page document.
        src = pymupdf.open(stream=data)
        try:
            page = src[0]
            scale = self._width / page.rect.width
            pix = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY
            )
            return pix.tobytes("png")
        finally:
            src.close()
