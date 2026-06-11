"""Extract node: download → transcribe content → save (step 2.2)."""

from doci.activities import DownloadMedia, ExtractContentImage, SaveResult
from doci.workflows.langgraph_document_mining_image.nodes.thumbnail import ImageNode
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


def make_extract_node(
    download: DownloadMedia, extract: ExtractContentImage, save: SaveResult
) -> ImageNode:
    """Build the extract-content node bound to its activities."""

    async def extract_node(state: DocumentMiningImageState) -> dict:
        data = await download(state["media_id"])
        markdown = await extract(data)
        ref = await save(
            state["execution_id"], state["part_id"], "extract.md", markdown
        )
        return {"extract_ref": ref}

    return extract_node
