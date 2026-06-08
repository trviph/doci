"""Scheduled media-maintenance tasks (label-based cron).

Each task is registered on the shared broker with a ``schedule`` label so
:class:`~taskiq.schedule_sources.LabelScheduleSource` kicks it on the configured
cron. The scheduler process only *enqueues* these; the worker executes them,
reading the shared clients built at ``WORKER_STARTUP`` via
:func:`doci.workflows.runtime.get_clients`.

Both sweeps are idempotent — they self-heal on the next tick — so they carry no
retry policy. Cron cadences are env-overridable under the ``CRON_MEDIA_*``
namespace.
"""

import os

from doci.taskiq import broker
from doci.workflows.runtime import get_clients

SOFT_DELETE_INVALID_CRON = os.getenv("CRON_MEDIA_SOFT_DELETE_INVALID", "0 * * * *")
PURGE_CRON = os.getenv("CRON_MEDIA_PURGE", "30 3 * * *")


@broker.task(schedule=[{"cron": SOFT_DELETE_INVALID_CRON}])
async def soft_delete_invalid_media() -> dict:
    """Soft-delete every ``INVALID`` media row into the purge grace window."""
    n = await get_clients().media.soft_delete_invalid()
    return {"soft_deleted": n}


@broker.task(schedule=[{"cron": PURGE_CRON}])
async def purge_soft_deleted_media() -> dict:
    """Hard-delete media past their purge deadline, S3 objects included."""
    n = await get_clients().media.purge_expired()
    return {"purged": n}
