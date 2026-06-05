"""Activity: extract a PDF page's content as Markdown via a vision LLM.

For graphic/scanned pages (images, complex layout) that the plain pymupdf4llm
path can't read. Renders the page to an image and asks a LangChain-wrapped vision
model (provider-agnostic) to transcribe it to Markdown. Sibling of
ExtractContentPdfPlain; same ``bytes -> str`` interface.
"""

import base64

import pymupdf
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from opentelemetry.trace import SpanKind

from doci.prompts import load
from doci.telemetry import traced, with_metrics, with_span

_SYSTEM = load("extract_content_pdf_graphic")

# LLM task profile for this activity (small/medium, data-mining). Override via
# DOCI_LLM_EXTRACT_PDF_GRAPHIC_* ; shared fallback DOCI_LLM_* .
LLM_TASK = "EXTRACT_PDF_GRAPHIC"
LLM_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"


@traced
class ExtractContentPdfGraphic:
    """Transcribe a PDF page image to Markdown using an injected vision LLM."""

    def __init__(self, model: BaseChatModel, *, dpi: int = 150) -> None:
        self._model = model
        self._zoom = dpi / 72.0

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> str:
        """Render the first page and return its Markdown transcription."""
        png_b64 = self._render_png_b64(data)
        message = HumanMessage(
            content=[
                {"type": "text", "text": "Transcribe this page to Markdown."},
                {
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": "image/png",
                    "data": png_b64,
                },
            ]
        )
        resp = await self._model.ainvoke([SystemMessage(_SYSTEM), message])
        return _as_text(resp.content)

    def _render_png_b64(self, data: bytes) -> str:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            pix = doc[0].get_pixmap(
                matrix=pymupdf.Matrix(self._zoom, self._zoom),
                colorspace=pymupdf.csRGB,
            )
            return base64.standard_b64encode(pix.tobytes("png")).decode("ascii")
        finally:
            doc.close()


def _as_text(content: object) -> str:
    """Extract plain text from a LangChain message ``content`` (str or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)
