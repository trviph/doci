"""Configuration for the TaskIQ broker.

Reads ``TASKIQ_BROKER_URL`` from the environment; falls back to Redis db 1
(the database reserved for the task-queue broker in this service). The remaining
fields tune the Redis Stream broker (consumer group, redelivery, stream length).
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskiqConfig:
    """Broker connection + Redis Stream tuning."""

    broker_url: str = "redis://localhost:6379/1"
    queue_name: str = "taskiq"  # stream key (db 1)
    consumer_group_name: str = "taskiq"
    # Min time a delivered-but-unacked message must sit idle before XAUTOCLAIM
    # reclaims + redelivers it. MUST exceed the longest task runtime, or a task
    # still running gets reclaimed and double-run. Generous default for LLM/PDF work.
    idle_timeout_ms: int = 30 * 60 * 1000  # 30 min
    # XACK clears the consumer group's PEL but NOT the stream itself — without a
    # cap the stream grows forever. Trimmed approximately (~) on XADD.
    stream_maxlen: int = 10_000
    # Release the XAUTOCLAIM lock if a worker dies mid-reclaim (else it can stay
    # locked indefinitely, blocking redelivery).
    unack_lock_timeout: float = 60.0  # seconds
    # Result backend (full per-task_id payloads) + developer task monitor (listable
    # lifecycle index). Both live in the broker db; keys self-expire after the TTL.
    result_prefix: str = "taskiq:result"
    result_ttl_s: int = 3 * 24 * 3600  # 3 days
    monitor_prefix: str = "taskmon"
    monitor_ttl_s: int = 3 * 24 * 3600  # 3 days
    # Worker runtime limits (process/concurrency), distinct from the broker/stream
    # tuning above. Default to a single worker process — one instance/pod runs one
    # worker — overriding taskiq's default of 2. ``max_threadpool_threads`` is for
    # sync tasks; ``None`` leaves taskiq's default in place.
    workers: int = 1
    max_async_tasks: int = 100
    max_threadpool_threads: int | None = None

    @classmethod
    def from_env(cls) -> "TaskiqConfig":
        """Build config from ``TASKIQ_*`` env vars."""
        ttl = 3 * 24 * 3600
        max_threads = os.getenv("TASKIQ_MAX_THREADPOOL_THREADS")
        return cls(
            broker_url=os.getenv("TASKIQ_BROKER_URL", "redis://localhost:6379/1"),
            queue_name=os.getenv("TASKIQ_QUEUE_NAME", "taskiq"),
            consumer_group_name=os.getenv("TASKIQ_CONSUMER_GROUP", "taskiq"),
            idle_timeout_ms=int(
                os.getenv("TASKIQ_IDLE_TIMEOUT_MS", str(30 * 60 * 1000))
            ),
            stream_maxlen=int(os.getenv("TASKIQ_STREAM_MAXLEN", "10000")),
            unack_lock_timeout=float(os.getenv("TASKIQ_UNACK_LOCK_TIMEOUT", "60")),
            result_prefix=os.getenv("TASKIQ_RESULT_PREFIX", "taskiq:result"),
            result_ttl_s=int(os.getenv("TASKIQ_RESULT_TTL_S", str(ttl))),
            monitor_prefix=os.getenv("TASKIQ_MONITOR_PREFIX", "taskmon"),
            monitor_ttl_s=int(os.getenv("TASKIQ_MONITOR_TTL_S", str(ttl))),
            workers=int(os.getenv("TASKIQ_WORKERS", "1")),
            max_async_tasks=int(os.getenv("TASKIQ_MAX_ASYNC_TASKS", "100")),
            max_threadpool_threads=int(max_threads) if max_threads else None,
        )
