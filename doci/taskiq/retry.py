"""Retry policy: retry failed tasks, except when they time out.

The retry *engine* is :class:`RetryUnlessTimeoutMiddleware`, registered once on
the broker. The *policy* is per task: a task opts in with the ``retry_on_error``
label (and tunes ``max_retries``), and enforces its own time budget with
``asyncio.wait_for``, raising :class:`TaskTimeout` when exceeded. The middleware
retries every other failure but lets a ``TaskTimeout`` fail terminally — a run
that's already too slow shouldn't be re-run just to time out again.
"""

from typing import Any

from taskiq import SmartRetryMiddleware
from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult


class TaskTimeout(Exception):
    """A task exceeded its own time budget. Excluded from retries."""


class RetryUnlessTimeoutMiddleware(SmartRetryMiddleware):
    """:class:`SmartRetryMiddleware` that never retries a :class:`TaskTimeout`."""

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        if isinstance(exception, TaskTimeout):
            return
        await super().on_error(message, result, exception)
