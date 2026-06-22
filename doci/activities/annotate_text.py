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

from doci.activities.fields import DossierSpec, FieldSpec
from doci.prompts import load
from doci.telemetry import traced, with_metrics, with_span

_SYSTEM = load("annotate_text")

# LLM task profile for this activity. Override via DOCI_LLM_ANNOTATE_TEXT_* ;
# shared fallback DOCI_LLM_* .
LLM_TASK = "ANNOTATE_TEXT"
LLM_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"
# Annotation is analysis (classify + extract facts), so it gets *some* reasoning
# ("low"). Keep a generous budget so the structured output never truncates.
# Env DOCI_LLM_* still overrides.
LLM_DEFAULT_MAX_TOKENS = 16000
LLM_DEFAULT_PARAMS = {"reasoning_effort": "low"}


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
    item_key: str | None = Field(
        default=None,
        description="when a dossier group is supplied, the key of the document "
        "type this text was classified as (null if none match)",
    )


def _user_prompt(
    text: str, fields: Sequence[FieldSpec] | None, dossier: DossierSpec | None
) -> str:
    """The per-call user message: instruction (+ classification or watchlist),
    then the document. With a ``dossier`` the model classifies the text to one of
    the dossier's document types and extracts the facts its ``look_for`` calls out."""
    if dossier is not None and dossier.items:
        catalog = "\n".join(
            f"- {it.key}: {it.name}"
            + (f" — {it.description}" if it.description else "")
            + (f"\n    look for: {it.look_for}" if it.look_for else "")
            for it in dossier.items
        )
        instruction = (
            f'This document is one document from the "{dossier.name}" dossier. '
            "Set `item_key` to a type's key only when this document's own "
            "title/heading/declared name — or content that clearly matches that "
            "type's description/“look for” note — identifies it as that type; "
            "otherwise set it to null. Never classify by topic or relatedness; "
            "do not guess. Then extract any audit-relevant facts the matched "
            f"type's “look for” note calls out into `facts`.\n\nDocument types:\n{catalog}"
        )
    else:
        instruction = "Annotate the document below."
        if fields:
            lines = "\n".join(
                f"- {f.name}: {f.hint}" if f.hint else f"- {f.name}" for f in fields
            )
            instruction += (
                f"\n\nFields to look for (extract into facts if present):\n{lines}"
            )
    return f"{instruction}\n\n<document>\n{text}\n</document>"


@traced
class AnnotateText:
    """Annotate a plain-text document into a structured TextAnnotation via an LLM."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model.with_structured_output(TextAnnotation)

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(
        self,
        text: str,
        fields: Sequence[FieldSpec] | None = None,
        dossier: DossierSpec | None = None,
    ) -> TextAnnotation:
        """Return a structured annotation of the ``text`` document.

        With a ``dossier`` the text is classified to one of its document types
        (``item_key``) and the facts that type's ``look_for`` calls out are
        extracted; otherwise ``fields`` is an optional flat watchlist extracted
        into ``facts``.
        """
        return await self._model.ainvoke(
            [SystemMessage(_SYSTEM), HumanMessage(_user_prompt(text, fields, dossier))]
        )
