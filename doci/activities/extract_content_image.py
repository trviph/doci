"""Activity: transcribe an image's content to Markdown via a vision LLM.

For graphic/scanned pages that the text-layer ``extract_content_pdf`` path can't
read: the caller renders a PDF page (or, later, a DOCX graphic) to an image, and
this asks a LangChain-wrapped vision model (provider-agnostic) to transcribe it to
Markdown. Takes image bytes (PNG/JPEG); same ``bytes -> str`` interface.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from opentelemetry.trace import SpanKind

from doci.activities._vision import image_message
from doci.prompts import load
from doci.telemetry import traced, with_metrics, with_span

_SYSTEM = load("extract_content_image")

# LLM task profile for this activity (small/medium, data-mining). Override via
# DOCI_LLM_EXTRACT_IMAGE_* ; shared fallback DOCI_LLM_* .
LLM_TASK = "EXTRACT_IMAGE"
LLM_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"


@traced
class ExtractContentImage:
    """Transcribe an image (PNG/JPEG) to Markdown using an injected vision LLM."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, image: bytes) -> str:
        """Return the image's content transcribed to Markdown."""
        resp = await self._model.ainvoke(
            [
                SystemMessage(_SYSTEM),
                image_message("Transcribe this image to Markdown.", image),
            ]
        )
        return _as_text(resp.content)


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
