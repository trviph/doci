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
from taskiq.api import run_scheduler_task
from taskiq.receiver import Receiver

import doci.telemetry  # noqa: F401
from commands.worker_mon import create_mon_app
from doci.api import create_app
from doci.scheduler import scheduler
from doci.taskiq.broker import broker

# Import task modules so their @broker.task / event handlers register on import.
import doci.workflows.langgraph_document_mining.task  # noqa: F401, E402
import doci.workflows.langgraph_document_mining_image.task  # noqa: F401, E402
import doci.scheduler.tasks  # noqa: F401, E402  (scheduled maintenance tasks)


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
    host = os.getenv("HOST", "localhost")
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host=host, port=int(os.getenv("PORT", "8000")))
    )
    # The dev task monitor shares this process's broker (the API app + receiver
    # start it), so it must not manage the broker lifecycle itself.
    mon_server = uvicorn.Server(
        uvicorn.Config(
            create_mon_app(manage_broker=False),
            host=host,
            port=int(os.getenv("MON_PORT", "8001")),
        )
    )

    # Run the HTTP server, the dev monitor, and the in-process worker together. If
    # any stops — a clean shutdown (Ctrl+C) or a worker startup failure — wind down
    # the others and re-raise any error so the process exits instead of hanging.
    finish = asyncio.Event()
    receiver_task = asyncio.create_task(_run_receiver(finish), name="taskiq-receiver")
    server_task = asyncio.create_task(server.serve(), name="uvicorn-server")
    mon_task = asyncio.create_task(mon_server.serve(), name="uvicorn-monitor")
    # The label-based scheduler kicks the maintenance tasks; it loops forever with
    # no stop signal, so it's cancelled explicitly during shutdown below.
    scheduler_task = asyncio.create_task(
        run_scheduler_task(scheduler), name="taskiq-scheduler"
    )
    tasks = (receiver_task, server_task, mon_task, scheduler_task)

    await asyncio.wait(set(tasks), return_when=asyncio.FIRST_COMPLETED)

    server.should_exit = True  # ask uvicorn to stop if it's still serving
    mon_server.should_exit = True
    finish.set()  # ask the receiver to stop if it's still listening
    scheduler_task.cancel()  # the scheduler loop only stops on cancellation
    await asyncio.gather(*tasks, return_exceptions=True)

    # Re-raise a worker/server failure so the process crashes instead of hanging.
    for task in tasks:
        if not task.cancelled() and task.exception() is not None:
            raise task.exception()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
