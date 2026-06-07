"""API + in-process worker for development / single-node deployments.

Runs the FastAPI app and a TaskIQ receiver in the same asyncio event loop.
For production at scale, run doci-api and doci-worker as separate processes.

Import order mirrors commands/worker.py: telemetry must be imported first so
TaskiqInstrumentor is active before doci.taskiq triggers broker construction.
"""

import asyncio
import os

import uvicorn
from taskiq.api.receiver import run_receiver_task

import doci.telemetry  # noqa: F401
from doci.api import create_app
from doci.taskiq.broker import broker

# Import task modules so their @broker.task / event handlers register on import.
import doci.workflows.langgraph_document_mining.task  # noqa: F401, E402


async def _serve() -> None:
    app = create_app()
    config = uvicorn.Config(
        app,
        host=os.getenv("HOST", "localhost"),
        port=int(os.getenv("PORT", "8000")),
    )
    server = uvicorn.Server(config)

    # Run the receiver as a background task alongside the HTTP server.
    # run_startup=True fires WORKER_STARTUP events; the FastAPI lifespan
    # independently fires CLIENT_STARTUP via broker.startup() in app.py.
    receiver_task = asyncio.create_task(run_receiver_task(broker, run_startup=True))

    try:
        await server.serve()
    finally:
        receiver_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
