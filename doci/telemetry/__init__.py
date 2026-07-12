import logging
import os

from openinference.instrumentation import TraceConfig
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from openinference.semconv.resource import ResourceAttributes
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from doci.globals import ENVIRONMENT, RUNTIME_ID, SERVICE_VERSION

# Pick the OTLP exporter transport from the standard OTEL_EXPORTER_OTLP_PROTOCOL
# env var. gRPC is the default (fast, bidirectional); "http/protobuf" is required
# by collectors that only speak OTLP/HTTP — e.g. Langfuse, whose OTLP endpoint is
# http://<host>:3000/api/public/otel. Instantiating a specific exporter class in
# code (rather than letting the SDK auto-configure) means the env var alone can't
# switch transports, so we honor it here. Endpoint and headers (e.g. the Basic
# auth header Langfuse needs) are still read from OTEL_EXPORTER_OTLP_* by the
# exporter itself, exactly as before.
if os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").startswith("http"):
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
else:
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter


def _signal_enabled(name: str) -> bool:
    """Whether an OTLP signal should be exported.

    Honors the standard ``OTEL_{METRICS,LOGS}_EXPORTER`` switch: setting it to
    ``none`` skips building that pipeline. Langfuse ingests *traces only*, so we
    turn metrics/logs off there to avoid periodic export failures against an
    endpoint that has no ``/v1/metrics`` or ``/v1/logs`` route. Traces are always
    exported.
    """
    return os.getenv(name, "otlp").strip().lower() != "none"


_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "doci")
_CUSTOM_RESOURCE = Resource.create(
    {
        "service.name": _SERVICE_NAME,
        "deployment.environment": ENVIRONMENT,
        "service.version": SERVICE_VERSION,
        "runtime.id": RUNTIME_ID,
        # OpenInference-native trace UIs (e.g. Phoenix) group traces into
        # projects by this resource attribute; default it to the OTel service
        # name so traces land in a named project instead of "default". Harmless
        # for backends that route by API key (e.g. Langfuse).
        ResourceAttributes.PROJECT_NAME: _SERVICE_NAME,
    }
)

# --- Traces ---
TRACER_PROVIDER = TracerProvider(resource=_CUSTOM_RESOURCE)
TRACER_PROVIDER.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(TRACER_PROVIDER)

# --- Metrics ---
# No metric reader when OTEL_METRICS_EXPORTER=none: the provider still serves
# in-process instruments (counters/histograms stay live) but nothing is exported.
_metric_readers = (
    [PeriodicExportingMetricReader(OTLPMetricExporter())]
    if _signal_enabled("OTEL_METRICS_EXPORTER")
    else []
)
METER_PROVIDER = MeterProvider(
    resource=_CUSTOM_RESOURCE,
    metric_readers=_metric_readers,
)
metrics.set_meter_provider(METER_PROVIDER)

# --- Logs ---
LOGGER_PROVIDER = LoggerProvider(resource=_CUSTOM_RESOURCE)
if _signal_enabled("OTEL_LOGS_EXPORTER"):
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

# Auto-instrument psycopg (psycopg3) so every query emits low-level DB spans bound
# to our provider (complements the higher-level @with_span on the Postgres client).
PsycopgInstrumentor().instrument(tracer_provider=TRACER_PROVIDER)

# Auto-instrument redis/valkey so every command emits low-level client spans
# bound to our provider (complements the higher-level @with_span on the KV client).
RedisInstrumentor().instrument(tracer_provider=TRACER_PROVIDER)

# Auto-instrument LangChain/LangGraph (callback-based) so each graph node and LLM
# call emits a span bound to our provider — complements the @with_span on the
# activities. Token usage, model name, and timing are always recorded; the raw
# prompt/response payloads (which are large and may carry PII or base64 images)
# are redacted unless DOCI_LLM_TRACE_CONTENT is explicitly enabled.
_TRACE_LLM_CONTENT = os.getenv("DOCI_LLM_TRACE_CONTENT", "").lower() in (
    "1",
    "true",
    "yes",
)
_LANGCHAIN_INSTRUMENTOR = LangChainInstrumentor()
_LANGCHAIN_INSTRUMENTOR.instrument(
    tracer_provider=TRACER_PROVIDER,
    config=TraceConfig(
        hide_inputs=not _TRACE_LLM_CONTENT,
        hide_outputs=not _TRACE_LLM_CONTENT,
    ),
)

# Auto-instrument taskiq so every broker constructed after this point gets the
# OpenTelemetryMiddleware injected, emitting send/execute spans and task metrics.
from taskiq.instrumentation import TaskiqInstrumentor  # noqa: E402

_TASKIQ_INSTRUMENTOR = TaskiqInstrumentor()
_TASKIQ_INSTRUMENTOR.instrument(
    tracer_provider=TRACER_PROVIDER,
    meter_provider=METER_PROVIDER,
)

# Register process/host runtime metrics (RAM, CPU, threads, file descriptors, GC)
# against the meter provider set above.
from doci.telemetry import runtime  # noqa: E402

runtime.instrument()


def shutdown() -> None:
    """Flush and close all telemetry providers. Call on application shutdown."""
    BotocoreInstrumentor().uninstrument()
    PsycopgInstrumentor().uninstrument()
    RedisInstrumentor().uninstrument()
    _LANGCHAIN_INSTRUMENTOR.uninstrument()
    _TASKIQ_INSTRUMENTOR.uninstrument()
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
    suppress_instrumentation,
    traced,
    untraced,
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
    "suppress_instrumentation",
    "untraced",
    "Report",
    "Counter",
    "Histogram",
    "UpDownCounter",
]
