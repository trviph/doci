"""Label-based TaskIQ scheduler.

The module-level ``scheduler`` singleton kicks the maintenance tasks defined in
:mod:`doci.scheduler.tasks` on their ``schedule`` labels, read by
:class:`~taskiq.schedule_sources.LabelScheduleSource` off the shared broker.
Importing this package registers those tasks on the broker, so running
``taskiq scheduler doci.scheduler:scheduler`` discovers them with no extra module
arguments.
"""

import doci.scheduler.tasks  # noqa: F401  (register scheduled tasks on the broker)
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from doci.taskiq import broker

scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])

__all__ = ["scheduler"]
