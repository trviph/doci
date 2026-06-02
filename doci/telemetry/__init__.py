import logging

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from doci.globals import ENVIRONMENT, RUNTIME_ID, SERVICE_VERSION

_CUSTOM_RESOURCE = Resource.create(
    {
        "deployment.environment": ENVIRONMENT,
        "service.version": SERVICE_VERSION,
        "runtime.id": RUNTIME_ID,
    }
)

# --- Traces ---
TRACER_PROVIDER = TracerProvider(resource=_CUSTOM_RESOURCE)
TRACER_PROVIDER.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(TRACER_PROVIDER)

# --- Metrics ---
_METRIC_READER = PeriodicExportingMetricReader(OTLPMetricExporter())
METER_PROVIDER = MeterProvider(
    resource=_CUSTOM_RESOURCE,
    metric_readers=[_METRIC_READER],
)
metrics.set_meter_provider(METER_PROVIDER)

# --- Logs ---
LOGGER_PROVIDER = LoggerProvider(resource=_CUSTOM_RESOURCE)
LOGGER_PROVIDER.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
set_logger_provider(LOGGER_PROVIDER)

# Bridge stdlib logging into the OTel log pipeline.
LOGGING_HANDLER = LoggingHandler(logger_provider=LOGGER_PROVIDER)
logging.getLogger().addHandler(LOGGING_HANDLER)

# Auto-instrument botocore/boto3 so every AWS/S3 call emits low-level client spans
# bound to our providers (complements the higher-level @with_span on ObjStore).
BotocoreInstrumentor().instrument(
    tracer_provider=TRACER_PROVIDER,
    meter_provider=METER_PROVIDER,
)

# Auto-instrument psycopg2 so every query emits low-level DB spans bound to our
# provider (complements the higher-level @with_span on the Postgres client).
# skip_dep_check: the dist is `psycopg2-binary`, but the check looks for `psycopg2`.
Psycopg2Instrumentor().instrument(tracer_provider=TRACER_PROVIDER, skip_dep_check=True)

# Auto-instrument redis/valkey so every command emits low-level client spans
# bound to our provider (complements the higher-level @with_span on the KV client).
RedisInstrumentor().instrument(tracer_provider=TRACER_PROVIDER)

# Register process/host runtime metrics (RAM, CPU, threads, file descriptors, GC)
# against the meter provider set above.
from doci.telemetry import runtime  # noqa: E402

runtime.instrument()


def shutdown() -> None:
    """Flush and close all telemetry providers. Call on application shutdown."""
    BotocoreInstrumentor().uninstrument()
    Psycopg2Instrumentor().uninstrument()
    RedisInstrumentor().uninstrument()
    runtime.uninstrument()
    TRACER_PROVIDER.shutdown()
    METER_PROVIDER.shutdown()
    LOGGER_PROVIDER.shutdown()


# Public decorator + metrics API. Imported here (after providers are registered
# above) so the decorators resolve the global providers without a circular import.
from doci.telemetry.decorators import (  # noqa: E402
    Counter,
    Histogram,
    Report,
    UpDownCounter,
    current_report,
    traced,
    with_metrics,
    with_span,
)

__all__ = [
    "TRACER_PROVIDER",
    "METER_PROVIDER",
    "LOGGER_PROVIDER",
    "LOGGING_HANDLER",
    "shutdown",
    "traced",
    "with_span",
    "with_metrics",
    "current_report",
    "Report",
    "Counter",
    "Histogram",
    "UpDownCounter",
]
