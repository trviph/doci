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
