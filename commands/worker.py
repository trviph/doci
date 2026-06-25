"""TaskIQ worker process entry point.

Import order is intentional: ``doci.telemetry`` must be fully initialised
(providers registered, ``TaskiqInstrumentor`` wrapping ``AsyncBroker.__init__``)
before ``doci.taskiq`` is imported so the broker is auto-instrumented at
construction time.
"""

import sys

import doci.telemetry  # noqa: F401
import doci.taskiq  # noqa: F401

# Import task modules so their @broker.task / event handlers register on import.
import doci.workflows.langgraph_audit.task  # noqa: F401
import doci.workflows.langgraph_document_mining.task  # noqa: F401
import doci.workflows.langgraph_document_mining_image.task  # noqa: F401
import doci.workflows.langgraph_document_mining_pdf.task  # noqa: F401
import doci.scheduler.tasks  # noqa: F401  (execute the scheduled maintenance tasks)
import taskiq.__main__

from doci.taskiq.config import TaskiqConfig


def main() -> None:
    cfg = TaskiqConfig.from_env()
    argv = [
        "worker",
        "doci.taskiq.broker:broker",
        "--workers",
        str(cfg.workers),
        "--max-async-tasks",
        str(cfg.max_async_tasks),
    ]
    if cfg.max_threadpool_threads is not None:
        argv += ["--max-threadpool-threads", str(cfg.max_threadpool_threads)]
    sys.argv[1:1] = argv
    taskiq.__main__.main()


if __name__ == "__main__":
    main()
