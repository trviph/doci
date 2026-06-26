"""Transcribe node: download once → extract ∥ annotate → save both (step 2).

Extraction (text transcription) and annotation (a vision pass) are independent,
so they run concurrently off a single shared download — replacing the old serial
``extract → annotate`` chain where each node re-downloaded the same blob. Folds
the former ``extract`` and ``annotate`` nodes into one. Trade-off: coarser
checkpoint granularity — a retry re-runs both passes — but both saves are
idempotent ``ON CONFLICT`` upserts, so re-running is harmless.
"""

import asyncio

from doci.activities import (
    AnnotateImage,
    DownloadMedia,
    ExtractContentImage,
    SaveResult,
)
from doci.activities.fields import DossierSpec
from doci.workflows.langgraph_document_mining_image.nodes.thumbnail import ImageNode
from doci.workflows.langgraph_document_mining_image.state import (
    DocumentMiningImageState,
)


def make_transcribe_node(
    download: DownloadMedia,
    extract: ExtractContentImage,
    annotate: AnnotateImage,
    save: SaveResult,
) -> ImageNode:
    """Build the transcribe node bound to its activities."""

    async def transcribe_node(state: DocumentMiningImageState) -> dict:
        data = await download(state["media_id"])
        ds = state.get("dossier_spec")
        dossier = DossierSpec.model_validate(ds) if ds else None

        markdown, annotation = await asyncio.gather(
            extract(data),
            annotate(data, dossier=dossier),
        )

        execution_id = state["execution_id"]
        part_id = state["part_id"]
        extract_ref = await save(execution_id, part_id, "extract.md", markdown)
        annotation_ref = await save(
            execution_id, part_id, "annotation.json", annotation.model_dump_json()
        )
        return {"extract_ref": extract_ref, "annotation_ref": annotation_ref}

    return transcribe_node
