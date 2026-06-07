"""Worker-side runtime for the workflow tasks.

The taskiq worker has no FastAPI lifespan, so the shared clients and the Valkey
checkpointer are built once on ``WORKER_STARTUP`` (released on shutdown) and
stashed on ``broker.state``. Both workflow tasks read them via the accessors here.
"""

from taskiq import TaskiqEvents, TaskiqState

from doci.bootstrap import Clients, build_clients, close_clients
from doci.taskiq import broker
from doci.workflows.checkpoint import ValkeySaver
from doci.workflows.checkpoint import aclose as aclose_saver
from doci.workflows.checkpoint import build_saver

_CLIENTS_ATTR = "doci_clients"
_SAVER_ATTR = "doci_checkpointer"


def get_clients() -> Clients:
    """The shared clients built at worker startup."""
    return getattr(broker.state, _CLIENTS_ATTR)


def get_saver() -> ValkeySaver:
    """The shared Valkey checkpointer built at worker startup."""
    return getattr(broker.state, _SAVER_ATTR)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _startup(state: TaskiqState) -> None:
    setattr(state, _CLIENTS_ATTR, build_clients())
    setattr(state, _SAVER_ATTR, build_saver())


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(state: TaskiqState) -> None:
    clients: Clients | None = getattr(state, _CLIENTS_ATTR, None)
    if clients is not None:
        await close_clients(clients)
    saver: ValkeySaver | None = getattr(state, _SAVER_ATTR, None)
    if saver is not None:
        await aclose_saver(saver)
