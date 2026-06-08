"""TaskIQ broker.

The module-level ``broker`` singleton is the shared broker instance for the
whole service. It is a Redis Stream broker (consumer-group based): delivery is
acknowledged and at-least-once — a message stays in the group's pending list
until the receiver acks it (after the task runs), and a dead worker's unacked
messages are reclaimed (XAUTOCLAIM) and redelivered. Tunables come from
:class:`TaskiqConfig`.

A result backend (full per-task_id payloads) and the developer task monitor
(:class:`TaskMonitorMiddleware`, a listable lifecycle index) are attached too;
both live in the broker db and self-expire. The monitor middleware is registered
*before* the retry middleware so a retried failure ends as ``queued`` rather than
``failed``.

Import ordering is critical: ``doci.telemetry`` must be imported before this
module so that ``TaskiqInstrumentor`` has already patched
``AsyncBroker.__init__`` before the broker is constructed here.
"""

from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from doci.taskiq.config import TaskiqConfig
from doci.taskiq.monitor import TaskMonitorMiddleware
from doci.taskiq.retry import RetryUnlessTimeoutMiddleware

_cfg = TaskiqConfig.from_env()
broker = RedisStreamBroker(
    _cfg.broker_url,
    queue_name=_cfg.queue_name,
    consumer_group_name=_cfg.consumer_group_name,
    idle_timeout=_cfg.idle_timeout_ms,  # XAUTOCLAIM min-idle, in milliseconds
    maxlen=_cfg.stream_maxlen,  # approximate (~) trim on XADD
    unacknowledged_lock_timeout=_cfg.unack_lock_timeout,
).with_result_backend(
    RedisAsyncResultBackend(
        _cfg.broker_url,
        prefix_str=_cfg.result_prefix,
        result_ex_time=_cfg.result_ttl_s,
    )
)

# Order matters: the monitor records failures in on_error, then the retry engine
# re-kicks (its post_send re-marks the task queued). Timeouts (TaskTimeout) never retry.
broker.add_middlewares(
    TaskMonitorMiddleware(
        _cfg.broker_url, prefix=_cfg.monitor_prefix, ttl=_cfg.monitor_ttl_s
    ),
    RetryUnlessTimeoutMiddleware(),
)
