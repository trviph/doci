"""Worker-side runtime for the workflow tasks.

The taskiq worker has no FastAPI lifespan, so the shared clients and the Valkey
checkpointer are built once on ``WORKER_STARTUP`` (released on shutdown) and
stashed on ``broker.state``. Both workflow tasks read them via the accessors here.
"""

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from taskiq import TaskiqEvents, TaskiqState

from doci.bootstrap import Clients, build_clients, close_clients
from doci.postgres.config import PostgresConfig
from doci.taskiq import broker
from doci.taskiq.config import TaskiqConfig
from doci.workflows.checkpoint import ValkeySaver
from doci.workflows.checkpoint import aclose as aclose_saver
from doci.workflows.checkpoint import build_saver
from doci.workflows.langgraph_document_mining_pdf.nodes import MAX_PAGE_CONCURRENCY
from doci.workflows.models import LangGraphMeta, WorkflowMetadata
from doci.workflows.service import WorkflowExecutionService

_CLIENTS_ATTR = "doci_clients"
_SAVER_ATTR = "doci_checkpointer"

_log = logging.getLogger(__name__)


def _concurrency_report(
    total_concurrency: int,
    page_concurrency: int,
    pool_max: int,
    pool_timeout: float,
) -> tuple[str, str | None]:
    """Boot summary of the concurrency↔pool relationship + an optional warning.

    The pool must serve every concurrent task's own DB calls *plus* its page
    fan-out — roughly ``total_concurrency × page_concurrency`` callers. When
    ``pool_max`` is below that, the surplus queue up to ``pool_timeout`` then
    raise ``PoolTimeout``. We don't auto-resize the pool here (it also bounds the
    Supavisor pooler); we surface the gap so operators raise it deliberately.
    """
    needed = total_concurrency * page_concurrency
    info = (
        f"worker concurrency: tasks={total_concurrency} × "
        f"page_fanout={page_concurrency} ⇒ ~{needed} concurrent DB callers; "
        f"pool_max={pool_max}, pool_timeout={pool_timeout}s"
    )
    warning: str | None = None
    if pool_max < needed:
        warning = (
            f"POSTGRES_POOL_MAX={pool_max} is below the ~{needed} connections the "
            f"page fan-out can demand (tasks {total_concurrency} × page_concurrency "
            f"{page_concurrency}); surplus callers queue up to {pool_timeout}s then "
            f"raise PoolTimeout. Raise POSTGRES_POOL_MAX toward {needed}."
        )
    return info, warning


def get_clients() -> Clients:
    """The shared clients built at worker startup."""
    return getattr(broker.state, _CLIENTS_ATTR)


def get_saver() -> ValkeySaver:
    """The shared Valkey checkpointer built at worker startup."""
    return getattr(broker.state, _SAVER_ATTR)


async def langgraph_meta(thread_id: str) -> LangGraphMeta:
    """Capture the latest checkpoint id + its expiry for ``thread_id``.

    Reads the saver directly (no graph needed), so it works in both the success
    and failure paths — including a failure that happened before the graph ran,
    where there is simply no checkpoint yet (``checkpoint_id`` stays ``None``).
    """
    saver = get_saver()
    tup = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
    checkpoint_id = (
        tup.config.get("configurable", {}).get("checkpoint_id") if tup else None
    )
    deadline = (
        datetime.now(timezone.utc) + timedelta(seconds=saver.ttl)
        if checkpoint_id is not None
        else None
    )
    return LangGraphMeta(
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        checkpoint_deadline=deadline,
    )


async def final_metadata(
    runs: WorkflowExecutionService, execution_id: UUID, thread_id: str
) -> WorkflowMetadata:
    """Current row metadata (keeps the taskiq id) with the latest checkpoint merged."""
    rec = await runs.get(execution_id)
    return replace(rec.metadata, langgraph=await langgraph_meta(thread_id))


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _startup(state: TaskiqState) -> None:
    clients = build_clients()
    await clients.postgres.open()

    taskiq_cfg = TaskiqConfig.from_env()
    pg_cfg = PostgresConfig.from_env()
    info, warning = _concurrency_report(
        taskiq_cfg.total_concurrency,
        MAX_PAGE_CONCURRENCY,
        pg_cfg.pool_max,
        pg_cfg.pool_timeout,
    )
    _log.info(info)
    if warning is not None:
        _log.warning(warning)

    setattr(state, _CLIENTS_ATTR, clients)
    setattr(state, _SAVER_ATTR, build_saver())


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(state: TaskiqState) -> None:
    clients: Clients | None = getattr(state, _CLIENTS_ATTR, None)
    if clients is not None:
        await close_clients(clients)
    saver: ValkeySaver | None = getattr(state, _SAVER_ATTR, None)
    if saver is not None:
        await aclose_saver(saver)
