"""Configuration for the TaskIQ broker.

Reads ``TASKIQ_BROKER_URL`` from the environment; falls back to Redis db 1
(the database reserved for the task-queue broker in this service).
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskiqConfig:
    """Broker connection configuration."""

    broker_url: str = "redis://localhost:6379/1"

    @classmethod
    def from_env(cls) -> "TaskiqConfig":
        """Build config from ``TASKIQ_BROKER_URL`` env var."""
        return cls(
            broker_url=os.getenv("TASKIQ_BROKER_URL", "redis://localhost:6379/1"),
        )
