"""Split node: download → burst into pages → store each as a PAGE media.

Pure-text pages are stored as their standalone single-page PDF; image pages are
rendered to PNG (so the image child graph can run on them) and stored as that
PNG. Closure-DI over the activities, mirroring the image workflow's nodes.
"""

from collections.abc import Awaitable, Callable

from doci.activities import DownloadMedia, RenderImagePdf, SplitPdf, UploadMedia
from doci.media import MediaType
from doci.media.mime import MIME_PDF
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
    upload: UploadMedia,
) -> PdfNode:
    """Build the split node bound to its activities."""

    async def split_node(state: DocumentMiningPdfState) -> dict:
        media_id = state["media_id"]
        data = await download(media_id)
        pages: list[PageRef] = []
        page_count = 0
        async for page in split(data):
            page_count = page.page_count
            kind = classify_page(page)
            if kind == "text":
                rec = await upload(
                    page.content,
                    parent_id=media_id,
                    type=MediaType.PAGE,
                    mime_type=MIME_PDF,
                )
            else:
                png = await render_image_pdf(page.content)
                rec = await upload(png, parent_id=media_id, type=MediaType.PAGE)
            pages.append(
                PageRef(page_number=page.page_number, kind=kind, page_media_id=rec.id)
            )
        return {"pages": pages, "page_count": page_count}

    return split_node
