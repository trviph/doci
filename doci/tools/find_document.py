"""Tool: is a given document type present in the dossier? (completeness probe)

Service-backed (factory). Bound to the mining ``execution_id``; reports which
pages were classified as ``item_key`` — and the contiguous page **range** those
pages span — the đủ-pass check for whether a required document is present.

``item_key`` is a per-page classification *hint*, not a document boundary: a
multi-page document's continuation pages often carry no label (no header on
page 2) or a different one, so the classified pages can undercount the real
document. The tool returns ``span`` (first→last classified page) and
``span_pages`` (every page in that range, labeled or not) so the agent reads the
whole document rather than trusting the labels.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.results import WorkflowResultService


def build_find_document(
    results: WorkflowResultService, execution_id: UUID
) -> StructuredTool:
    async def find_document(item_key: str) -> dict:
        """Check whether the dossier contains a page classified as document type
        `item_key`. Returns `present` plus the pages involved.

        The page `item_key` is an advisory classification, NOT a document
        boundary — continuation pages of a multi-page document are often
        unlabeled or mislabeled. So:
        - `classified_pages`: the page numbers labeled `item_key` (advisory; may
          undercount).
        - `span`: `[first, last]` classified page — the contiguous range the
          document most likely occupies.
        - `span_pages`: every page within `span` (with its part_id and its own
          `item_key`, which may be null/other) — read across these to cover the
          whole document, and confirm each page's role from its text/image
          rather than from the label.
        """
        pages = await results.page_index(execution_id)
        matched = [p for p in pages if p.item_key == item_key]
        numbered = [p.page_number for p in matched if p.page_number is not None]
        span = [min(numbered), max(numbered)] if numbered else None
        span_pages: list[dict] = []
        if span is not None:
            lo, hi = span
            span_pages = [
                {
                    "part_id": str(p.part_id),
                    "page_number": p.page_number,
                    "item_key": p.item_key,
                }
                for p in pages
                if p.page_number is not None and lo <= p.page_number <= hi
            ]
        return {
            "ok": True,
            "item_key": item_key,
            "present": bool(matched),
            "classified_pages": [p.page_number for p in matched],
            "span": span,
            "span_pages": span_pages,
        }

    return tool(find_document)
