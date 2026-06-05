"""Activity: auto-annotate an image (vision LLM).

Classifies what an image *is* (screenshot, chart, presentation, scanned document,
...), describes it, and lists the distinct visual elements it contains (flat — no
nesting). Source-agnostic — the caller renders a PDF page (or, later, a DOCX
graphic) to an image first.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, Field

from doci.activities._vision import image_message
from doci.prompts import load
from doci.telemetry import traced, with_metrics, with_span

_SYSTEM = load("annotate_image")

# LLM task profile for this activity. Override via DOCI_LLM_ANNOTATE_IMAGE_* ;
# shared fallback DOCI_LLM_* .
LLM_TASK = "ANNOTATE_IMAGE"
LLM_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"


class VisualElement(BaseModel):
    """One visual element on the image."""

    category: str = Field(
        description="concise type, e.g. chart, table, photo, logo, text block"
    )
    description: str = Field(description="what this element shows")
    key_features: list[str] = Field(
        default_factory=list, description="distinguishing features"
    )


class ImageAnnotation(BaseModel):
    """Annotation of an image as a whole plus a flat list of its visual elements."""

    category: str = Field(
        description="what the image is, e.g. screenshot, chart, presentation slide, scanned document"
    )
    description: str = Field(description="overall description of the image")
    key_features: list[str] = Field(
        default_factory=list, description="what makes the image stand out"
    )
    elements: list[VisualElement] = Field(
        default_factory=list,
        description="all distinct visual elements on the image (flat, not nested)",
    )


@traced
class AnnotateImage:
    """Annotate an image into a structured ImageAnnotation via a vision LLM."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(ImageAnnotation)

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, image: bytes) -> ImageAnnotation:
        """Return a structured annotation of the ``image`` (PNG/JPEG bytes)."""
        return await self._model.ainvoke(
            [SystemMessage(_SYSTEM), image_message("Annotate this image.", image)]
        )
