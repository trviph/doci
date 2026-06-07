"""Extract node: download → transcribe content → save (step 2.2)."""

from doci.activities import DownloadMedia, ExtractContentImage
from doci.workflows.langgraph_document_mining_image.nodes.thumbnail import ImageNode
from doci.workflows.langgraph_document_mining_image.save import save_result
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


def make_extract_node(
    download: DownloadMedia, extract: ExtractContentImage
) -> ImageNode:
    """Build the extract-content node bound to its activities."""

    async def extract_node(state: DocumentMiningImageState) -> dict:
        media_id = state["media_id"]
        data = await download(media_id)
        markdown = await extract(data)
        return {"extract_ref": save_result(media_id, "extract.md", markdown)}

    return extract_node
