"""Enqueue an audit run for a specific mining execution.

Shared by the auto-chain (mining success enqueues an audit for its own run) and
the manual ``POST /audits`` endpoint. The audit is bound to a **specific**
``mining_execution_id`` — never "the latest" — so each mined dossier maps to a
deterministic audit with no race.
"""

from uuid import UUID, uuid4

from doci.workflows.langgraph_audit.task import run_audit
from doci.workflows.models import LangGraphMeta, WorkflowInput, WorkflowMetadata
from doci.workflows.service import WorkflowExecutionService


async def enqueue_audit(
    runs: WorkflowExecutionService,
    *,
    document_id: UUID,
    mining_execution_id: UUID,
    dossier_key: str,
    language: str = "English",
) -> UUID:
    """Create an audit ``workflow_execution`` and enqueue ``run_audit`` for it.

    ``language`` is the output language for the findings/verdict prose (default
    English). Returns the new audit execution id.
    """
    thread_id = uuid4()
    execution_id = await runs.create(
        workflow="audit",
        entity_type="document",
        entity_id=document_id,
        input=WorkflowInput(document_id=document_id, dossier_key=dossier_key),
        metadata=WorkflowMetadata(langgraph=LangGraphMeta(thread_id=str(thread_id))),
    )
    await run_audit.kiq(
        str(document_id),
        str(execution_id),
        str(mining_execution_id),
        str(thread_id),
        dossier_key,
        language,
    )
    return execution_id
