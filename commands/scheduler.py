"""TaskIQ scheduler process entry point (``doci-scheduler``).

Kicks the label-scheduled maintenance tasks on their cron cadence. Like the
worker, it only needs the broker — task bodies run on the worker, not here.

Import order mirrors ``commands/worker.py``: ``doci.telemetry`` must be fully
initialised before ``doci.taskiq`` so the broker is auto-instrumented at
construction. Importing ``doci.scheduler`` registers the scheduled tasks and
builds the ``scheduler`` instance.
"""

import sys

import doci.telemetry  # noqa: F401
import doci.taskiq  # noqa: F401
import doci.scheduler  # noqa: F401  (registers scheduled tasks + the scheduler)
import taskiq.__main__


def main() -> None:
    sys.argv[1:1] = ["scheduler", "doci.scheduler:scheduler"]
    taskiq.__main__.main()


if __name__ == "__main__":
    main()
