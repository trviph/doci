"""API + in-process worker for development / single-node deployments.

Runs the FastAPI app and a TaskIQ receiver in the same asyncio event loop.
For production at scale, run doci-api and doci-worker as separate processes.

Import order mirrors commands/worker.py: telemetry must be imported first so
TaskiqInstrumentor is active before doci.taskiq triggers broker construction.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import uvicorn
from taskiq.receiver import Receiver

import doci.telemetry  # noqa: F401
from doci.api import create_app
from doci.taskiq.broker import broker

# Import task modules so their @broker.task / event handlers register on import.
import doci.workflows.langgraph_document_mining.task  # noqa: F401, E402
import doci.workflows.langgraph_document_mining_image.task  # noqa: F401, E402


async def _run_receiver(finish: asyncio.Event) -> None:
    """Run the TaskIQ receiver once, letting startup failures propagate.

    Unlike ``taskiq.api.receiver.run_receiver_task``, this does NOT wrap
    ``listen`` in a retry loop: a failing ``WORKER_STARTUP`` (e.g. an
    unreachable database) crashes the process instead of silently retrying
    forever. ``run_startup=True`` fires WORKER_STARTUP; the FastAPI lifespan
    independently fires CLIENT_STARTUP via ``broker.startup()`` in app.py.
    """
    broker.is_worker_process = True
    with ThreadPoolExecutor() as executor:
        receiver = Receiver(broker=broker, executor=executor, run_startup=True)
        await receiver.listen(finish)


async def _serve() -> None:
    app = create_app()
    config = uvicorn.Config(
        app,
        host=os.getenv("HOST", "localhost"),
        port=int(os.getenv("PORT", "8000")),
    )
    server = uvicorn.Server(config)

    # Run the HTTP server and the in-process worker together. If either stops —
    # a clean server shutdown (Ctrl+C) or a worker startup failure — wind down
    # the other and re-raise any error so the process exits instead of hanging.
    finish = asyncio.Event()
    receiver_task = asyncio.create_task(_run_receiver(finish), name="taskiq-receiver")
    server_task = asyncio.create_task(server.serve(), name="uvicorn-server")

    await asyncio.wait(
        {receiver_task, server_task}, return_when=asyncio.FIRST_COMPLETED
    )

    server.should_exit = True  # ask uvicorn to stop if it's still serving
    finish.set()  # ask the receiver to stop if it's still listening
    await asyncio.gather(receiver_task, server_task, return_exceptions=True)

    # Re-raise a worker/server failure so the process crashes instead of hanging.
    for task in (receiver_task, server_task):
        if not task.cancelled() and task.exception() is not None:
            raise task.exception()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
