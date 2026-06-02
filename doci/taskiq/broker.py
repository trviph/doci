"""TaskIQ broker.

The module-level ``broker`` singleton is the shared broker instance for the
whole service.  Import ordering is critical: ``doci.telemetry`` must be imported
before this module so that ``TaskiqInstrumentor`` has already patched
``AsyncBroker.__init__`` before the broker is constructed here.
"""

from taskiq_redis import ListQueueBroker

from doci.taskiq.config import TaskiqConfig

broker = ListQueueBroker(TaskiqConfig.from_env().broker_url)
