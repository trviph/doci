"""Graph state + per-page classification for the PDF document-mining workflow.

A PDF is split into pages; each page is classified into a ``kind`` that selects
its processing path. Only small references live in state — never the page bytes —
so checkpoints stay tiny; each node downloads the bytes it needs.
"""

from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from doci.activities import PdfPage

PageKind = Literal["text", "image"]


@dataclass(frozen=True, slots=True)
class PageRef:
    """A split page materialized as a ``document_part``, plus its kind."""

    page_number: int  # 1-based index within the source document
    kind: PageKind  # which processing path the page takes
    page_media_id: UUID  # the stored page blob (single-page PDF, or PNG if image)
    part_id: UUID  # the document_part row (target for the page's thumbnail)


def classify_page(page: PdfPage) -> PageKind:
    """Classify a split page: ``text`` only when it's pure text.

    Any embedded image, any annotation/widget (highlights, signatures, form
    fields, ...), or no extractable text routes to the ``image`` path — the
    vision pipeline reads what the text-layer extractor can't.
    """
    if page.text_len > 0 and page.image_count == 0 and not page.has_annotations:
        return "text"
    return "image"


class DocumentMiningPdfState(TypedDict, total=False):
    """State threaded through the PDF-mining child graph."""

    media_id: UUID  # input: the original PDF blob (shared with the parent graph)
    document_id: UUID  # input: the document (parts are created under it)
    execution_id: UUID  # input (the workflow_execution row; used when saving results)
    group_spec: dict | None  # input: dossier GroupSpec (dict) for group-aware annotate
    page_count: int  # total pages (set by the split node)
    pages: list[PageRef]  # split pages + classification (set by the split node)
    page_results: list[dict]  # per-page outputs (set by the process node)
