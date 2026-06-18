"""Tool: a viewable image URL for one page (fallback visual check).

Service-backed (factory). Most visual evidence (signatures, stamps, IMEI) is
captured as facts at annotation time; this is the fallback for when the agent
must actually look. Returns a short-lived presigned URL for the page's image.
"""

from uuid import UUID

from langchain_core.tools import StructuredTool, tool

from doci.media import MediaService
from doci.postgres import Postgres


def build_get_page_image(media: MediaService, postgres: Postgres) -> StructuredTool:
    async def get_page_image(part_id: str) -> dict:
        """Get a presigned image URL for a page by part_id — only when you must
        visually inspect it (most evidence is already in the annotation facts)."""
        try:
            pid = UUID(part_id)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"{part_id!r} is not a valid part_id (UUID)."}
        row = await postgres.fetch_one(
            "SELECT media_id FROM document_part WHERE id = %s", [pid]
        )
        if row is None or row.get("media_id") is None:
            return {"ok": False, "error": f"no page image for part {part_id}."}
        rec = await media.get(row["media_id"])
        url = await media.view_url(rec.object_key)
        return {"ok": True, "part_id": part_id, "image_url": url, "mime_type": rec.mime_type}

    return tool(get_page_image)
