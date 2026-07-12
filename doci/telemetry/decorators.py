"""Declarative telemetry decorators.

Lets business code stay free of OpenTelemetry imports: tracing and metrics are
applied with decorators, and custom metrics are recorded through declared
descriptors via a per-call ``Report``.

Providers are resolved through the global OTel API (``trace.get_tracer`` /
``metrics.get_meter``), which the package ``__init__`` has already registered.
Resolving lazily here keeps this module free of a circular import with it.
"""

import functools
import inspect
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator, ParamSpec, TypeVar, overload

from opentelemetry import context as _otel_ctx
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.utils import _SUPPRESS_INSTRUMENTATION_KEY
from opentelemetry.metrics import Counter as _OTelCounter
from opentelemetry.metrics import Histogram as _OTelHistogram
from opentelemetry.metrics import UpDownCounter as _OTelUpDownCounter
from opentelemetry.trace import SpanKind, Tracer
from opentelemetry.util.types import Attributes

_P = ParamSpec("_P")
_R = TypeVar("_R")
_C = TypeVar("_C", bound=type)
_Number = int | float


@contextmanager
def suppress_instrumentation() -> Iterator[None]:
    """Suppress OTel auto-instrumentation (library client spans) for the block.

    Sets the standard ``_SUPPRESS_INSTRUMENTATION_KEY`` in the OTel context, which
    the botocore/psycopg/redis instrumentors honor by skipping span creation. Use
    it to silence high-frequency, low-value library spans — e.g. the Valkey
    checkpointer's per-step HSET/HKEYS, or TaskIQ's idle broker polling — that
    would otherwise flood the trace UI and bury the meaningful spans.
    """
    token = _otel_ctx.attach(_otel_ctx.set_value(_SUPPRESS_INSTRUMENTATION_KEY, True))
    try:
        yield
    finally:
        _otel_ctx.detach(token)


def untraced(fn: Callable[_P, _R]) -> Callable[_P, _R]:
    """Decorate an async function to run with auto-instrumentation suppressed."""

    @functools.wraps(fn)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with suppress_instrumentation():
            return await fn(*args, **kwargs)  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]


_DEFAULT_TRACER: Tracer = trace.get_tracer("doci")
_DEFAULT_METER = metrics.get_meter("doci")


# region 1. Class tracer + 2. span decorator
class _Holder:
    """Mutable cell holding the tracer a span wrapper should use.

    ``with_span`` runs at method-definition time, before the owning class
    exists, so it cannot know the class tracer yet. Each wrapper carries a
    holder that ``traced`` fills in once it sees the class.
    """

    __slots__ = ("tracer",)

    def __init__(self) -> None:
        self.tracer: Tracer | None = None


@overload
def traced(cls: _C) -> _C: ...
@overload
def traced(cls: None = ..., *, name: str | None = ...) -> Callable[[_C], _C]: ...


def traced(
    cls: _C | None = None, *, name: str | None = None
) -> _C | Callable[[_C], _C]:
    """Class decorator: give the class its own named tracer.

    Binds every ``@with_span``-decorated method on the class to that tracer.
    Usable bare (``@traced``) or parameterized (``@traced(name="...")``).
    """

    def wrap(cls: _C) -> _C:
        tracer = trace.get_tracer(name or cls.__qualname__)
        cls.__otel_tracer__ = tracer
        for attr in vars(cls).values():
            func = (
                attr.__func__ if isinstance(attr, (staticmethod, classmethod)) else attr
            )
            holder: _Holder | None = getattr(func, "__otel_span_holder__", None)
            if holder is not None:
                holder.tracer = tracer
        return cls

    return wrap(cls) if cls is not None else wrap


def with_span(
    name: str | None = None,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Attributes = None,
    record_exception: bool = True,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Open a span around the call.

    Uses the owning class's tracer when present (see ``traced``), else the
    global default tracer. ``kind`` models the span's role —
    ``SpanKind.CLIENT`` for outbound HTTP/RPC, ``PRODUCER``/``CONSUMER`` for
    message queues, ``SERVER`` for inbound — and ``attributes`` carries the
    matching semantic-convention fields. Works on sync and async callables.
    """

    def decorate(func: Callable[_P, _R]) -> Callable[_P, _R]:
        holder = _Holder()
        span_name = name or func.__qualname__

        def _tracer(args: tuple[Any, ...]) -> Tracer:
            if holder.tracer is not None:
                return holder.tracer
            if args:
                owner_tracer = getattr(args[0], "__otel_tracer__", None)
                if owner_tracer is not None:
                    return owner_tracer
            return _DEFAULT_TRACER

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                with _tracer(args).start_as_current_span(
                    span_name,
                    kind=kind,
                    attributes=attributes,
                    record_exception=record_exception,
                ):
                    return await func(*args, **kwargs)

        else:

            @functools.wraps(func)
            def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                with _tracer(args).start_as_current_span(
                    span_name,
                    kind=kind,
                    attributes=attributes,
                    record_exception=record_exception,
                ):
                    return func(*args, **kwargs)

        wrapper.__otel_span_holder__ = holder
        return wrapper  # type: ignore[return-value]

    return decorate


# endregion


# region 3. Declared metrics + gather-and-report
class _Metric:
    """Descriptor for a single metric, declared once at module level.

    The underlying OTel instrument is created lazily on first emit and cached,
    so declaring a metric is import-order-safe and free.
    """

    def __init__(self, name: str, *, unit: str = "1", description: str = "") -> None:
        self.name = name
        self.unit = unit
        self.description = description

    def _emit(self, value: _Number, attributes: Attributes) -> None:
        raise NotImplementedError


class Counter(_Metric):
    """Monotonically increasing count."""

    @functools.cached_property
    def _instrument(self) -> _OTelCounter:
        return _DEFAULT_METER.create_counter(
            self.name, unit=self.unit, description=self.description
        )

    def _emit(self, value: _Number, attributes: Attributes) -> None:
        self._instrument.add(value, attributes)


class UpDownCounter(_Metric):
    """Count that can go up or down."""

    @functools.cached_property
    def _instrument(self) -> _OTelUpDownCounter:
        return _DEFAULT_METER.create_up_down_counter(
            self.name, unit=self.unit, description=self.description
        )

    def _emit(self, value: _Number, attributes: Attributes) -> None:
        self._instrument.add(value, attributes)


class Histogram(_Metric):
    """Distribution of recorded values."""

    @functools.cached_property
    def _instrument(self) -> _OTelHistogram:
        return _DEFAULT_METER.create_histogram(
            self.name, unit=self.unit, description=self.description
        )

    def _emit(self, value: _Number, attributes: Attributes) -> None:
        self._instrument.record(value, attributes)


_AttrKey = tuple[tuple[str, Any], ...]


class Report:
    """Per-call accumulator for declared metrics.

    Business code records measurements through it; ``with_metrics`` flushes
    them to their instruments once on function exit. Counters with identical
    attribute sets are summed; histograms are recorded individually.
    """

    def __init__(self) -> None:
        # counter metric -> {attrs_key: [attrs_dict, summed_value]}
        self._counters: dict[_Metric, dict[_AttrKey, list[Any]]] = {}
        # histogram metric -> [(attrs_dict, value), ...]
        self._observations: dict[_Metric, list[tuple[dict[str, Any], _Number]]] = {}

    def record(self, metric: _Metric, value: _Number = 1, **attrs: Any) -> None:
        """Gather a measurement against a declared ``metric``."""
        if isinstance(metric, Histogram):
            self._observations.setdefault(metric, []).append((attrs, value))
        else:
            key: _AttrKey = tuple(sorted(attrs.items()))
            bucket = self._counters.setdefault(metric, {})
            if key in bucket:
                bucket[key][1] += value
            else:
                bucket[key] = [attrs, value]

    def _flush(self) -> None:
        for metric, bucket in self._counters.items():
            for attrs, value in bucket.values():
                metric._emit(value, attrs)
        for metric, observations in self._observations.items():
            for attrs, value in observations:
                metric._emit(value, attrs)


_current_report: ContextVar[Report | None] = ContextVar(
    "doci_current_report", default=None
)


def current_report() -> Report:
    """Return the active ``Report`` inside a ``@with_metrics`` scope."""
    report = _current_report.get()
    if report is None:
        raise RuntimeError("current_report() called outside a @with_metrics scope")
    return report


# Auto metrics shared across all decorated operations; tagged with the
# `operation` and `outcome` attributes to keep cardinality manageable.
_OP_DURATION = Histogram(
    "doci.operation.duration", unit="ms", description="Operation duration"
)
_OP_CALLS = Counter("doci.operation.calls", description="Operation invocations")


def with_metrics(
    name: str | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Record duration/call/outcome metrics and expose a per-call ``Report``.

    The ``Report`` (reachable via ``current_report()``) collects declared
    metrics during the call; everything is emitted once on exit. Works on sync
    and async callables.
    """

    def decorate(func: Callable[_P, _R]) -> Callable[_P, _R]:
        operation = name or func.__qualname__

        def _finish(report: Report, start: float, error: bool) -> None:
            outcome = "error" if error else "ok"
            attrs = {"operation": operation, "outcome": outcome}
            _OP_DURATION._emit((time.perf_counter() - start) * 1000.0, attrs)
            _OP_CALLS._emit(1, attrs)
            report._flush()

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                report = Report()
                token: Token[Report | None] = _current_report.set(report)
                start = time.perf_counter()
                error = False
                try:
                    return await func(*args, **kwargs)
                except BaseException:
                    error = True
                    raise
                finally:
                    _finish(report, start, error)
                    _current_report.reset(token)

        else:

            @functools.wraps(func)
            def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                report = Report()
                token: Token[Report | None] = _current_report.set(report)
                start = time.perf_counter()
                error = False
                try:
                    return func(*args, **kwargs)
                except BaseException:
                    error = True
                    raise
                finally:
                    _finish(report, start, error)
                    _current_report.reset(token)

        return wrapper  # type: ignore[return-value]

    return decorate


# endregion
