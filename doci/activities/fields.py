"""Shared ``FieldSpec`` — the watchlist item the annotate activities accept.

A ``FieldSpec`` names an attribute the caller wants extracted into the
annotation's ``facts`` (with an optional hint on what to look for). It is the
common shape produced by the user data layer's document-group items and consumed
by :class:`AnnotateImage` / :class:`AnnotateText`, so it lives here rather than
being redefined per activity.
"""

from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    """A field the caller wants extracted from a document, if present."""

    name: str = Field(
        description="attribute name to extract; becomes the fact's subject"
    )
    hint: str | None = Field(
        default=None, description="optional note on what to look for or where"
    )


class DossierItemSpec(BaseModel):
    """One candidate document type within a dossier, for classification."""

    key: str = Field(description="stable key of this document type")
    name: str = Field(description="human name, e.g. 'VAT Invoice'")
    description: str | None = Field(
        default=None, description="what this document is / how to recognize it"
    )
    look_for: str | None = Field(
        default=None,
        description="plaintext note on what to look for / extract from this document",
    )


class DossierSpec(BaseModel):
    """A dossier handed to annotate: classify the page to one item, then extract
    the facts its ``look_for`` calls out. Built by the user data layer from a
    ``dossier_def`` and its ``document_def`` rows."""

    key: str
    name: str
    items: list[DossierItemSpec] = Field(default_factory=list)
