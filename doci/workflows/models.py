"""Value objects for workflow executions (framework-agnostic).

A ``workflow_execution`` row is an engine- and domain-agnostic record of one
workflow run. Its own columns describe the run in the abstract (which workflow,
which object it's about, lifecycle status, timings); everything
implementation-specific lives in three *versioned* JSONB blobs:

* ``input``    — what was submitted (e.g. the media id).
* ``result``   — the outcome: ``output`` on success, ``error`` on failure.
* ``metadata`` — engine bookkeeping, namespaced per engine (``taskiq`` job id,
  ``langgraph`` thread/checkpoint).

Each blob carries a semantic ``version`` string ``"vMAJOR.MINOR[.PATCH]"``. A
reader accepts any blob whose *major* matches its own: minor/patch drift (a
field added, or removed) parses without error because blobs are rebuilt
field-by-field with defaults. A differing *major* (a field's type/meaning
changed) raises :class:`ValueError`. Bump minor when adding an optional field,
major when changing a field's type/meaning.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

#: Current blob versions. Bump minor for additive changes, major for breaking ones.
WORKFLOW_INPUT_VERSION = "v1.0"
WORKFLOW_RESULT_VERSION = "v1.0"
WORKFLOW_METADATA_VERSION = "v1.0"


class WorkflowStatus(IntEnum):
    QUEUED = 0  # row created at trigger; taskiq job enqueued
    RUNNING = 1  # worker has started the graph
    SUCCEEDED = 2  # graph completed
    FAILED = 3  # graph raised


# region semver helpers
def _major(version: str) -> int:
    """Major number of a ``"vMAJOR.MINOR[.PATCH]"`` string."""
    return int(version.lstrip("vV").split(".", 1)[0])


def _require_compatible(stored: str, current: str) -> None:
    """Raise if ``stored`` and ``current`` differ in major version."""
    if _major(stored) != _major(current):
        raise ValueError(
            f"incompatible blob version {stored!r}: reader expects major of {current!r}"
        )


def _dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string (or pass through ``None``/``datetime``)."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# endregion


@dataclass(frozen=True, slots=True)
class WorkflowInput:
    """Snapshot of what was submitted to the workflow."""

    media_id: UUID
    version: str = WORKFLOW_INPUT_VERSION

    def to_json(self) -> dict[str, Any]:
        return {"version": self.version, "media_id": str(self.media_id)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "WorkflowInput":
        version = data.get("version", WORKFLOW_INPUT_VERSION)
        _require_compatible(version, WORKFLOW_INPUT_VERSION)
        return cls(media_id=UUID(str(data["media_id"])), version=version)


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Outcome of a run — ``output`` on success, ``error`` on failure."""

    output: dict[str, Any] | None = None
    error: str | None = None
    version: str = WORKFLOW_RESULT_VERSION

    def to_json(self) -> dict[str, Any]:
        return {"version": self.version, "output": self.output, "error": self.error}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "WorkflowResult":
        version = data.get("version", WORKFLOW_RESULT_VERSION)
        _require_compatible(version, WORKFLOW_RESULT_VERSION)
        return cls(output=data.get("output"), error=data.get("error"), version=version)


@dataclass(frozen=True, slots=True)
class TaskiqMeta:
    """The taskiq job that runs the execution."""

    task_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"task_id": self.task_id}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "TaskiqMeta":
        return cls(task_id=data.get("task_id"))


@dataclass(frozen=True, slots=True)
class LangGraphMeta:
    """The LangGraph thread/checkpoint the execution runs on."""

    thread_id: str
    checkpoint_id: str | None = None
    checkpoint_deadline: datetime | None = None  # when the checkpoint self-expires

    def to_json(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_deadline": _iso(self.checkpoint_deadline),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "LangGraphMeta":
        return cls(
            thread_id=data["thread_id"],
            checkpoint_id=data.get("checkpoint_id"),
            checkpoint_deadline=_dt(data.get("checkpoint_deadline")),
        )


@dataclass(frozen=True, slots=True)
class WorkflowMetadata:
    """Engine/runtime bookkeeping for an execution."""

    taskiq: TaskiqMeta = field(default_factory=TaskiqMeta)
    langgraph: LangGraphMeta | None = None
    retry_count: int = 0
    version: str = WORKFLOW_METADATA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "taskiq": self.taskiq.to_json(),
            "langgraph": self.langgraph.to_json() if self.langgraph else None,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "WorkflowMetadata":
        version = data.get("version", WORKFLOW_METADATA_VERSION)
        _require_compatible(version, WORKFLOW_METADATA_VERSION)
        lg = data.get("langgraph")
        return cls(
            taskiq=TaskiqMeta.from_json(data.get("taskiq") or {}),
            langgraph=LangGraphMeta.from_json(lg) if lg else None,
            retry_count=data.get("retry_count", 0),
            version=version,
        )


@dataclass(frozen=True, slots=True)
class WorkflowExecutionRecord:
    """A row of the ``workflow_execution`` table."""

    id: UUID
    workflow: str
    entity_type: str
    entity_id: UUID
    status: WorkflowStatus
    input: WorkflowInput
    result: WorkflowResult | None
    metadata: WorkflowMetadata
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "WorkflowExecutionRecord":
        return cls(
            id=row["id"],
            workflow=row["workflow"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            status=WorkflowStatus(row["status"]),
            input=WorkflowInput.from_json(row["input"]),
            result=(
                WorkflowResult.from_json(row["result"])
                if row["result"] is not None
                else None
            ),
            metadata=WorkflowMetadata.from_json(row["metadata"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
