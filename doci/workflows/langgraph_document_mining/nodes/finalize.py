"""First node: finalize an uploaded document and classify its supported type.

Delegates validation to the ``FinalizeDocument`` activity
(``DocumentService.finalize``, which validates MIME + size) and maps the
resulting ``mime_type`` to a ``DocumentType``. Built as a closure over the
injected activity, mirroring the constructor-injection style used by the
services/activities.
"""

from collections.abc import Awaitable, Callable

from doci.activities import FinalizeDocument
from doci.workflows.langgraph_document_mining.state import (
    DocumentMiningState,
    classify,
)

FinalizeNode = Callable[[DocumentMiningState], Awaitable[dict]]


def make_finalize_node(finalize: FinalizeDocument) -> FinalizeNode:
    """Build the finalize+classify node bound to a ``FinalizeDocument`` activity.

    Surfaces the original blob's ``media_id`` into state so the routed child graph
    (which mines that blob) has it without another lookup.
    """

    async def finalize_node(state: DocumentMiningState) -> dict:
        doc = await finalize(state["document_id"])
        return {
            "media_id": doc.media_id,
            "mime_type": doc.mime_type,
            "document_type": classify(doc.mime_type),
        }

    return finalize_node
