"""Tool: show a page's image to the model (fallback visual check).

Service-backed (factory). Most evidence (signatures, stamps, IMEI) is captured as
facts at annotation time or in the page's transcribed text (e.g. `<signature>`
tokens); this is the fallback for when the agent must actually look. Returns the
page image as a content block the (multimodal) model can view — used only when the
facts and the extracted text can't verify something. Never raises.
"""

import base64
from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.media import MediaService
from doci.postgres import Postgres


def build_get_page_image(media: MediaService, postgres: Postgres) -> StructuredTool:
    async def get_page_image(part_id: str):
        """Look at a page's image by part_id — only when you must visually inspect
        it (most evidence is already in the annotation facts). Returns the image
        for you to view."""
        try:
            pid = UUID(part_id)
        except ValueError, TypeError:
            return {"ok": False, "error": f"{part_id!r} is not a valid part_id (UUID)."}
        row = await postgres.fetch_one(
            "SELECT media_id FROM document_part WHERE id = %s", [pid]
        )
        if row is None or row.get("media_id") is None:
            return {"ok": False, "error": f"no page image for part {part_id}."}
        rec = await media.get(row["media_id"])
        data = await media.download(row["media_id"])
        b64 = base64.b64encode(data).decode("ascii")
        mime = rec.mime_type or "image/png"
        return [
            {"type": "text", "text": f"Page image for part {part_id}:"},
            {"type": "image", "source_type": "base64", "mime_type": mime, "data": b64},
        ]

    return tool(get_page_image)
