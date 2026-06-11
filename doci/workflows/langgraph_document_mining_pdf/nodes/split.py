"""Split node: download → burst into pages → materialize each as a document part.

Pure-text pages are stored as their standalone single-page PDF; image pages are
rendered to PNG (so the image child graph can run on them) and stored as that
PNG. Each page is created idempotently via ``DocumentService.ensure_part`` keyed
by its page locator, so a rerun reuses the existing part instead of re-uploading.
"""

from collections.abc import Awaitable, Callable

from doci.activities import DownloadMedia, RenderImagePdf, SplitPdf
from doci.documents import DocumentService, PartKind, page_locator
from doci.media.mime import MIME_PDF, MIME_PNG
from doci.workflows.langgraph_document_mining_pdf.state import (
    DocumentMiningPdfState,
    PageRef,
    classify_page,
)

PdfNode = Callable[[DocumentMiningPdfState], Awaitable[dict]]


def make_split_node(
    download: DownloadMedia,
    split: SplitPdf,
    render_image_pdf: RenderImagePdf,
    documents: DocumentService,
) -> PdfNode:
    """Build the split node bound to its activities + the documents service."""

    async def split_node(state: DocumentMiningPdfState) -> dict:
        document_id = state["document_id"]
        data = await download(state["media_id"])
        pages: list[PageRef] = []
        page_count = 0
        async for page in split(data):
            page_count = page.page_count
            kind = classify_page(page)
            content = page.content  # bind for the deferred render closure

            if kind == "text":

                async def render(c: bytes = content) -> tuple[bytes, str]:
                    return c, MIME_PDF

                part_kind = PartKind.TEXT
            else:

                async def render(c: bytes = content) -> tuple[bytes, str]:
                    return await render_image_pdf(c), MIME_PNG

                part_kind = PartKind.IMAGE

            part = await documents.ensure_part(
                document_id,
                locator=page_locator(page.page_number),
                kind=part_kind,
                render=render,
                page_number=page.page_number,
            )
            pages.append(
                PageRef(
                    page_number=page.page_number,
                    kind=kind,
                    page_media_id=part.media_id,
                    part_id=part.id,
                )
            )
        await documents.set_page_count(document_id, page_count)
        return {"pages": pages, "page_count": page_count}

    return split_node
