"""Activity: split a PDF into single-page PDFs, one yielded per page.

Bursts the document page by page. Each yielded ``PdfPage`` carries the bytes of a
standalone one-page ``application/pdf`` (ready to store as a ``MediaType.PAGE``
derivative) plus cheap classification signals — extractable-text length, embedded
-image count, annotation presence — so a downstream classify stage can label the
page without re-parsing. Rendering pages to images / OCR are separate concerns.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pymupdf


@dataclass(frozen=True, slots=True)
class PdfPage:
    """One page of a split PDF, as a standalone single-page PDF + classify signals."""

    page_number: int  # 1-based index within the source document
    page_count: int  # total pages in the source document
    content: bytes  # a complete one-page application/pdf
    text_len: int  # chars of extractable text (whitespace-stripped); ~0 => scanned
    image_count: int  # number of embedded images on the page
    has_annotations: bool  # an overlay/annotation is present


class SplitPdf:
    """Split a PDF and yield each page as a standalone single-page PDF."""

    async def __call__(self, data: bytes) -> AsyncIterator[PdfPage]:
        for page in self._iter_pages(data):
            yield page

    def _iter_pages(self, data: bytes) -> Iterator[PdfPage]:
        src = pymupdf.open(stream=data, filetype="pdf")
        try:
            total = src.page_count
            for i in range(total):
                page = src[i]
                text_len = len(page.get_text().strip())
                image_count = len(page.get_images())
                has_annotations = next(page.annots(), None) is not None
                dst = pymupdf.open()
                try:
                    dst.insert_pdf(src, from_page=i, to_page=i)
                    content = dst.tobytes()
                finally:
                    dst.close()
                yield PdfPage(
                    page_number=i + 1,
                    page_count=total,
                    content=content,
                    text_len=text_len,
                    image_count=image_count,
                    has_annotations=has_annotations,
                )
        finally:
            src.close()
