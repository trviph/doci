"""Activity: auto-annotate a plain-text document (LLM).

Classifies what a text document *is* (email, contract, statement of work, report,
...), describes it, and extracts a flat list of discrete ``facts`` for a later
compare/audit step. The text analog of ``annotate_image`` — same generic
annotation shape and optional field watchlist, for already-extracted text.
"""

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, Field

from doci.prompts import load
from doci.telemetry import traced, with_metrics, with_span

_SYSTEM = load("annotate_text")

# LLM task profile for this activity. Override via DOCI_LLM_ANNOTATE_TEXT_* ;
# shared fallback DOCI_LLM_* .
LLM_TASK = "ANNOTATE_TEXT"
LLM_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"


class TextFact(BaseModel):
    """A discrete, audit-relevant value the document asserts."""

    subject: str = Field(
        description="what the fact is about — a short attribute name, e.g. title, date, quantity, price"
    )
    value: str = Field(
        description="the value as found, e.g. 2026-06-05, present, 1043, $1,200"
    )
    source: str = Field(
        description="verbatim quote of the relevant text from the document"
    )


class TextAnnotation(BaseModel):
    """Annotation of a plain-text document plus a flat list of its facts."""

    category: str = Field(
        description="what the text is, e.g. email, contract, statement of work, report, invoice"
    )
    description: str = Field(description="overall description of the document")
    key_features: list[str] = Field(
        default_factory=list, description="what makes the document stand out"
    )
    facts: list[TextFact] = Field(
        default_factory=list,
        description="discrete audit-relevant facts the document asserts (flat)",
    )


class FieldSpec(BaseModel):
    """A field the caller wants extracted from the document, if present."""

    name: str = Field(
        description="attribute name to extract; becomes the fact's subject"
    )
    hint: str | None = Field(
        default=None, description="optional note on what to look for or where"
    )


def _user_prompt(text: str, fields: Sequence[FieldSpec] | None) -> str:
    """The per-call user message: instruction, optional watchlist, then the document."""
    prompt = "Annotate the document below."
    if fields:
        lines = "\n".join(
            f"- {f.name}: {f.hint}" if f.hint else f"- {f.name}" for f in fields
        )
        prompt += f"\n\nFields to look for (extract into facts if present):\n{lines}"
    return f"{prompt}\n\n<document>\n{text}\n</document>"


@traced
class AnnotateText:
    """Annotate a plain-text document into a structured TextAnnotation via an LLM."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(TextAnnotation)

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(
        self, text: str, fields: Sequence[FieldSpec] | None = None
    ) -> TextAnnotation:
        """Return a structured annotation of the ``text`` document.

        ``fields`` is an optional watchlist of attributes the caller wants
        extracted into ``facts`` when present in the text.
        """
        return await self._model.ainvoke(
            [SystemMessage(_SYSTEM), HumanMessage(_user_prompt(text, fields))]
        )
