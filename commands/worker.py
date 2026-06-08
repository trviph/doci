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
import doci.workflows.langgraph_document_mining.task  # noqa: F401
import doci.workflows.langgraph_document_mining_image.task  # noqa: F401
import doci.scheduler.tasks  # noqa: F401  (execute the scheduled maintenance tasks)
import taskiq.__main__


def main() -> None:
    sys.argv[1:1] = ["worker", "doci.taskiq.broker:broker"]
    taskiq.__main__.main()


if __name__ == "__main__":
    main()
