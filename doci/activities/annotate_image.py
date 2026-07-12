"""Activity: auto-annotate an image (vision LLM).

Classifies what an image *is* (screenshot, chart, presentation, scanned document,
...), describes it, and lists the distinct visual elements it contains (flat — no
nesting). Source-agnostic — the caller renders a PDF page (or, later, a DOCX
graphic) to an image first.
"""

from collections.abc import Sequence
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, Field

from doci.activities._vision import image_message
from doci.activities.fields import DossierSpec, FieldSpec
from doci.prompts import load
from doci.telemetry import traced, with_metrics, with_span

_SYSTEM = load("annotate_image")
_REFLECT_SYSTEM = load("annotate_image_reflect")

# LLM task profile for this activity. Override via DOCI_LLM_ANNOTATE_IMAGE_* ;
# shared fallback DOCI_LLM_* .
LLM_TASK = "ANNOTATE_IMAGE"
LLM_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"
# Annotation is analysis (classify + extract facts), so it gets *some* reasoning
# ("low") — unlike OCR transcription, which wants minimal. Keep a generous budget
# so the structured output never truncates. Env DOCI_LLM_* still overrides.
LLM_DEFAULT_MAX_TOKENS = 16000
LLM_DEFAULT_PARAMS = {"reasoning_effort": "low"}

# Optional reflection pass — a separately-configured, stronger model that
# critiques and revises the first pass. Own task so its model/tokens/reasoning
# tune independently via DOCI_LLM_ANNOTATE_IMAGE_REFLECT_* .
LLM_REFLECT_TASK = "ANNOTATE_IMAGE_REFLECT"
LLM_REFLECT_DEFAULT_MODEL = "openai:gpt-5-mini-2025-08-07"
LLM_REFLECT_DEFAULT_MAX_TOKENS = 16000
LLM_REFLECT_DEFAULT_PARAMS = {"reasoning_effort": "medium"}
# Hard ceiling on critique→revise rounds, independent of any model signal. 1 = a
# single review pass; raising it re-reviews the revised annotation.
LLM_REFLECT_MAX_ITERS = 1


class VisualElement(BaseModel):
    """One visual element on the image."""

    category: str = Field(
        description="concise type, e.g. chart, table, photo, logo, text block"
    )
    description: str = Field(description="what this element shows")
    key_features: list[str] = Field(
        default_factory=list, description="distinguishing features"
    )


class Fact(BaseModel):
    """A discrete, audit-relevant value the image asserts or shows.

    Extracted at annotation time so a later compare step can match facts against
    requirements without re-reading the image.
    """

    subject: str = Field(
        description="what the fact is about — a short attribute name, e.g. title, date, quantity, price"
    )
    value: str = Field(
        description="the value as found, e.g. blue, present, 1043, 1200x600"
    )
    evidence: Literal["stated", "visual"] = Field(
        description="stated = printed as text/number on the page; visual = seen in the image"
    )
    source: str = Field(
        description="verbatim quote or short locator for where this came from"
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
    facts: list[Fact] = Field(
        default_factory=list,
        description="discrete audit-relevant facts the image asserts or shows (flat)",
    )
    item_key: str | None = Field(
        default=None,
        description="when a dossier group is supplied, the key of the document "
        "type this image was classified as (null if none match)",
    )


def _fields_block(fields: Sequence[FieldSpec]) -> str:
    return "\n".join(
        f"- {f.name}: {f.hint}" if f.hint else f"- {f.name}" for f in fields
    )


def _user_prompt(
    fields: Sequence[FieldSpec] | None, dossier: DossierSpec | None
) -> str:
    """The per-call user instruction.

    With a ``dossier`` the model classifies the image to one of its document
    types (``item_key``) and extracts the facts that type's ``look_for`` calls
    out; otherwise it annotates with an optional flat 'fields to look for' watchlist.
    """
    if dossier is not None and dossier.items:
        catalog = "\n".join(
            f"- {it.key}: {it.name}"
            + (f" — {it.description}" if it.description else "")
            + (f"\n    look for: {it.look_for}" if it.look_for else "")
            for it in dossier.items
        )
        return (
            f'This image is one document from the "{dossier.name}" dossier. Set '
            "`item_key` to a type's key only when this page's own visible "
            "title/heading/letterhead/declared name — or content that clearly "
            "matches that type's description/“look for” note — identifies it as "
            "that type; otherwise set it to null. Never classify by subject "
            "matter or relatedness; do not guess. Then extract any audit-relevant "
            "facts the matched type's “look for” note calls out into `facts`."
            f"\n\nDocument types:\n{catalog}"
        )
    prompt = "Annotate this image."
    if fields:
        prompt += (
            f"\n\nFields to look for (extract into facts if present):"
            f"\n{_fields_block(fields)}"
        )
    return prompt


def _reflect_prompt(
    fields: Sequence[FieldSpec] | None,
    dossier: DossierSpec | None,
    annotation: ImageAnnotation,
) -> str:
    """The reflect instruction: the original instruction, then the first-pass
    annotation to verify and correct (the image travels in the same message)."""
    return (
        f"{_user_prompt(fields, dossier)}\n\n"
        "<first_pass_annotation>\n"
        f"{annotation.model_dump_json()}\n"
        "</first_pass_annotation>"
    )


@traced
class AnnotateImage:
    """Annotate an image into a structured ImageAnnotation via a vision LLM."""

    def __init__(
        self,
        model: BaseChatModel,
        reflect_model: BaseChatModel | None = None,
        reflect_max_iters: int = LLM_REFLECT_MAX_ITERS,
    ) -> None:
        self._model = model.with_structured_output(ImageAnnotation)
        # None ⇒ reflection unavailable (the env-level gate lives in deps.py).
        self._reflect_model = (
            reflect_model.with_structured_output(ImageAnnotation)
            if reflect_model is not None
            else None
        )
        self._reflect_max_iters = reflect_max_iters

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(
        self,
        image: bytes,
        fields: Sequence[FieldSpec] | None = None,
        dossier: DossierSpec | None = None,
        reflect: bool = False,
    ) -> ImageAnnotation:
        """Return a structured annotation of the ``image`` (PNG/JPEG bytes).

        With a ``dossier`` the image is classified to one of its document types
        (``item_key``) and the facts that type's ``look_for`` calls out are
        extracted; otherwise ``fields`` is an optional flat watchlist extracted
        into ``facts``. When ``reflect`` is set *and* a reflect model was
        supplied, a bounded critique→revise pass corrects the first-pass output.
        """
        annotation = await self._model.ainvoke(
            [
                SystemMessage(_SYSTEM),
                image_message(_user_prompt(fields, dossier), image),
            ]
        )
        if self._reflect_model is not None and reflect:
            for _ in range(self._reflect_max_iters):
                annotation = await self._reflect_model.ainvoke(
                    [
                        SystemMessage(_REFLECT_SYSTEM),
                        image_message(
                            _reflect_prompt(fields, dossier, annotation), image
                        ),
                    ]
                )
        return annotation
