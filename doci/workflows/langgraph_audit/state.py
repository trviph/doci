"""State threaded through the audit graph."""

from typing import TypedDict
from uuid import UUID


class AuditState(TypedDict, total=False):
    """Inputs for one audit run (all set at invocation; nodes read them)."""

    document_id: UUID  # input: the audited document
    mining_execution_id: UUID  # input: the mining run whose results to audit
    audit_execution_id: UUID  # input: this audit run (findings/verdict hang off it)
    dossier_key: str  # input: the dossier to audit against
