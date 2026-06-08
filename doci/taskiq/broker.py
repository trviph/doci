"""TaskIQ broker.

The module-level ``broker`` singleton is the shared broker instance for the
whole service. It is a Redis Stream broker (consumer-group based): delivery is
acknowledged and at-least-once — a message stays in the group's pending list
until the receiver acks it (after the task runs), and a dead worker's unacked
messages are reclaimed (XAUTOCLAIM) and redelivered. Tunables come from
:class:`TaskiqConfig`.

Import ordering is critical: ``doci.telemetry`` must be imported before this
module so that ``TaskiqInstrumentor`` has already patched
``AsyncBroker.__init__`` before the broker is constructed here.
"""

from taskiq_redis import RedisStreamBroker

from doci.taskiq.config import TaskiqConfig
from doci.taskiq.retry import RetryUnlessTimeoutMiddleware

_cfg = TaskiqConfig.from_env()
broker = RedisStreamBroker(
    _cfg.broker_url,
    queue_name=_cfg.queue_name,
    consumer_group_name=_cfg.consumer_group_name,
    idle_timeout=_cfg.idle_timeout_ms,  # XAUTOCLAIM min-idle, in milliseconds
    maxlen=_cfg.stream_maxlen,  # approximate (~) trim on XADD
    unacknowledged_lock_timeout=_cfg.unack_lock_timeout,
)

# Retry engine only — whether/how many retries is a per-task label
# (retry_on_error / max_retries); timeouts (TaskTimeout) are never retried.
broker.add_middlewares(RetryUnlessTimeoutMiddleware())
