"""Process node: fan out over the split pages, bounded by a semaphore.

Each page runs its path concurrently (capped at ``max_concurrency`` to respect
LLM rate limits): pure-text pages extract → annotate → thumbnail in-line; image
pages are handed to the embedded image child graph, each under its own
per-page checkpoint thread derived from the run's ``thread_id``.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from doci.activities import (
    AnnotateText,
    CreateThumbPdf,
    DownloadMedia,
    ExtractContentPdf,
    SaveResult,
    UploadMedia,
)
from doci.media import MediaType
from doci.workflows.langgraph_document_mining_pdf.state import (
    DocumentMiningPdfState,
    PageRef,
)

ProcessNode = Callable[[DocumentMiningPdfState, RunnableConfig], Awaitable[dict]]

# Pages process concurrently, bounded so vision-heavy runs don't blow LLM rate
# limits. ~1.3 min/page measured => wall-clock ~ 1.3 * ceil(pages / concurrency).
MAX_PAGE_CONCURRENCY = int(os.getenv("DOCI_PDF_PAGE_CONCURRENCY", "4"))


def make_process_node(
    download: DownloadMedia,
    upload: UploadMedia,
    extract_pdf: ExtractContentPdf,
    annotate_text: AnnotateText,
    create_thumb_pdf: CreateThumbPdf,
    save: SaveResult,
    image_graph: CompiledStateGraph,
    *,
    max_concurrency: int = MAX_PAGE_CONCURRENCY,
) -> ProcessNode:
    """Build the per-page processing node bound to its activities + image graph."""

    async def _text_page(page: PageRef, execution_id: UUID) -> dict:
        data = await download(page.page_media_id)
        markdown = await extract_pdf(data)
        annotation = await annotate_text(markdown)
        thumb = await create_thumb_pdf(data)
        rec = await upload(thumb, parent_id=page.page_media_id, type=MediaType.THUMB)
        return {
            "page_number": page.page_number,
            "kind": page.kind,
            "page_media_id": page.page_media_id,
            "thumb_media_id": rec.id,
            "extract_ref": await save(
                execution_id, page.page_media_id, "extract.md", markdown
            ),
            "annotation_ref": await save(
                execution_id,
                page.page_media_id,
                "annotation.json",
                annotation.model_dump_json(),
            ),
        }

    async def _image_page(page: PageRef, thread_id: str, execution_id: UUID) -> dict:
        res = await image_graph.ainvoke(
            {"media_id": page.page_media_id, "execution_id": execution_id},
            config={"configurable": {"thread_id": f"{thread_id}:p{page.page_number}"}},
        )
        return {
            "page_number": page.page_number,
            "kind": page.kind,
            "page_media_id": page.page_media_id,
            "thumb_media_id": res.get("thumb_media_id"),
            "extract_ref": res.get("extract_ref"),
            "annotation_ref": res.get("annotation_ref"),
        }

    async def process_node(
        state: DocumentMiningPdfState, config: RunnableConfig
    ) -> dict:
        thread_id = config["configurable"]["thread_id"]
        execution_id = state["execution_id"]
        sem = asyncio.Semaphore(max_concurrency)

        async def handle(page: PageRef) -> dict:
            async with sem:
                if page.kind == "text":
                    return await _text_page(page, execution_id)
                return await _image_page(page, thread_id, execution_id)

        results = await asyncio.gather(*(handle(p) for p in state["pages"]))
        results.sort(key=lambda r: r["page_number"])
        return {"page_results": results}

    return process_node
