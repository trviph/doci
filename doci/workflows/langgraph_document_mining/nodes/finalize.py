"""First node: finalize an uploaded media and classify its supported type.

Delegates validation to the ``FinalizeMedia`` activity (MediaService.finalize,
which validates MIME + size) and maps the resulting ``mime_type`` to a
``DocumentType``. Built as a closure over the injected activity, mirroring the
constructor-injection style used by the services/activities.
"""

from collections.abc import Awaitable, Callable

from doci.activities import FinalizeMedia
from doci.workflows.langgraph_document_mining.state import (
    DocumentMiningState,
    classify,
)

FinalizeNode = Callable[[DocumentMiningState], Awaitable[dict]]


def make_finalize_node(finalize: FinalizeMedia) -> FinalizeNode:
    """Build the finalize+classify node bound to a ``FinalizeMedia`` activity."""

    async def finalize_node(state: DocumentMiningState) -> dict:
        rec = await finalize(state["media_id"])
        return {
            "mime_type": rec.mime_type,
            "document_type": classify(rec.mime_type),
        }

    return finalize_node
