"""Span logic of the `find_document` completeness probe.

`item_key` is an advisory per-page label, not a document boundary; the tool
must surface the contiguous page `span` (and every page in it, labeled or not)
so the agent reads continuation pages it would otherwise miss.
"""

import asyncio
from uuid import uuid4

from doci.results.models import PageRef
from doci.tools.find_document import build_find_document


class _FakeResults:
    def __init__(self, pages: list[PageRef]) -> None:
        self._pages = pages

    async def page_index(self, execution_id):  # noqa: ANN001 - test double
        return self._pages


def _page(num: int | None, item_key: str | None) -> PageRef:
    return PageRef(
        part_id=uuid4(),
        page_number=num,
        locator=f"p{(num or 0):05d}",
        item_key=item_key,
        category=None,
    )


def _run(pages: list[PageRef], item_key: str) -> dict:
    tool_obj = build_find_document(_FakeResults(pages), uuid4())
    return asyncio.run(tool_obj.ainvoke({"item_key": item_key}))


def test_span_covers_unlabeled_continuation_pages():
    # A PR whose page 2 lost its label still spans pages 1-3.
    pages = [_page(1, "pr"), _page(2, None), _page(3, "pr")]
    r = _run(pages, "pr")
    assert r["present"] is True
    assert r["classified_pages"] == [1, 3]  # advisory: undercounts
    assert r["span"] == [1, 3]
    assert [p["page_number"] for p in r["span_pages"]] == [1, 2, 3]
    # the dropped continuation page is surfaced (unlabeled) for reading
    assert r["span_pages"][1]["item_key"] is None


def test_absent_document_has_no_span():
    pages = [_page(1, "invoice"), _page(2, "invoice")]
    r = _run(pages, "pr")
    assert r["present"] is False
    assert r["span"] is None
    assert r["span_pages"] == []


def test_span_does_not_swallow_other_documents_outside_range():
    # pr on 1-2, invoice on 3-4: each span stays within its own range.
    pages = [_page(1, "pr"), _page(2, "pr"), _page(3, "invoice"), _page(4, "invoice")]
    pr = _run(pages, "pr")
    inv = _run(pages, "invoice")
    assert pr["span"] == [1, 2]
    assert [p["page_number"] for p in pr["span_pages"]] == [1, 2]
    assert inv["span"] == [3, 4]
    assert [p["page_number"] for p in inv["span_pages"]] == [3, 4]
