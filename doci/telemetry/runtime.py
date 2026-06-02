"""Runtime resource instrumentation.

Two layers:

* **System / process metrics** — RAM, CPU, thread count, open file descriptors,
  context switches, and per-generation GC — from the upstream system-metrics
  instrumentation (psutil-backed). Registered at telemetry import time via
  ``instrument()``; pull-based, so they cost nothing between scrapes.

* **asyncio metrics** — the active task count and event-loop scheduling lag, the
  Python-async analogs of "how many routines are live" and "is the loop
  blocked". These need the running event loop, so they are started from inside
  it (the API lifespan) via ``start_asyncio_metrics`` and stopped with
  ``stop_asyncio_metrics``.

The meter provider is resolved lazily through the global OTel API, which the
package ``__init__`` registers before any of these run — same pattern as the
library auto-instrumentors.
"""

import asyncio
from collections.abc import Iterable

from opentelemetry import metrics
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.metrics import Histogram as _OTelHistogram

# A curated slice of the upstream default config: the runtime-health signals
# (RAM, CPU, threads, file descriptors, context switches, GC). Disk/network/swap
# series are dropped — those belong to host monitoring, not the app process.
# The cpython.gc.* series add per-generation collection detail on top of the
# coarse process.runtime.gc_count.
_SYSTEM_METRICS_CONFIG: dict[str, list[str] | None] = {
    "system.cpu.utilization": ["idle", "user", "system"],
    "system.memory.usage": ["used", "free", "cached"],
    "system.memory.utilization": ["used", "free", "cached"],
    "process.cpu.time": ["user", "system"],
    "process.cpu.utilization": ["user", "system"],
    "process.memory.usage": None,
    "process.memory.virtual": None,
    "process.open_file_descriptor.count": None,
    "process.thread.count": None,
    "process.context_switches": ["involuntary", "voluntary"],
    "process.runtime.gc_count": None,
    "cpython.gc.collections": None,
    "cpython.gc.collected_objects": None,
    "cpython.gc.uncollectable_objects": None,
}

# Seconds between event-loop lag samples. Each sample is one short sleep, so the
# probe's own footprint is negligible.
_LAG_PROBE_INTERVAL = 1.0

_METER = metrics.get_meter("doci.runtime")
_SYSTEM_INSTRUMENTOR: SystemMetricsInstrumentor | None = None
_lag_histogram: _OTelHistogram | None = None
_lag_probe_task: asyncio.Task[None] | None = None
# Captured from inside the running loop (see ``start_asyncio_metrics``); read
# from the metric reader's thread, which has no running loop of its own.
_loop: asyncio.AbstractEventLoop | None = None


# region System / process metrics
def instrument() -> None:
    """Register system/process instruments against the global meter provider.

    Idempotent. Called once at telemetry import time, after the providers are
    set. Also defines the asyncio instruments (task gauge + lag histogram),
    which stay dormant until a loop is bound by ``start_asyncio_metrics``.
    """
    global _SYSTEM_INSTRUMENTOR, _lag_histogram
    if _SYSTEM_INSTRUMENTOR is not None:
        return
    _SYSTEM_INSTRUMENTOR = SystemMetricsInstrumentor(config=_SYSTEM_METRICS_CONFIG)
    _SYSTEM_INSTRUMENTOR.instrument(meter_provider=metrics.get_meter_provider())
    _METER.create_observable_gauge(
        "doci.runtime.asyncio.tasks",
        callbacks=[_observe_asyncio_tasks],
        unit="{task}",
        description="Active (not-done) asyncio tasks on the event loop",
    )
    _lag_histogram = _METER.create_histogram(
        "doci.runtime.asyncio.event_loop.lag",
        unit="ms",
        description="Event-loop scheduling delay beyond a requested sleep",
    )


def uninstrument() -> None:
    """Tear down system/process instruments. Call on telemetry shutdown."""
    global _SYSTEM_INSTRUMENTOR
    if _SYSTEM_INSTRUMENTOR is not None:
        _SYSTEM_INSTRUMENTOR.uninstrument()
        _SYSTEM_INSTRUMENTOR = None


# endregion


# region asyncio metrics
def _observe_asyncio_tasks(options: CallbackOptions) -> Iterable[Observation]:
    """Report the active asyncio task count for the bound event loop.

    Runs on the metric reader's thread, so it reads the loop captured by
    ``start_asyncio_metrics`` rather than a running loop. Yields nothing until a
    loop is bound, after it closes, or if the task set mutates mid-snapshot — a
    skipped scrape is harmless for a gauge.
    """
    loop = _loop
    if loop is None or loop.is_closed():
        return ()
    try:
        tasks = asyncio.all_tasks(loop)
    except RuntimeError:
        return ()
    return (Observation(len(tasks)),)


async def _lag_probe(interval: float) -> None:
    """Sample event-loop scheduling lag until cancelled.

    Each iteration requests a fixed sleep; any overshoot beyond it is time the
    loop spent unable to service this callback — i.e. it was busy or blocked.
    Recorded to the ``instrument()``-defined histogram so tail latency is
    visible, not just the mean.
    """
    assert _lag_histogram is not None, "instrument() must run before the lag probe"
    loop = asyncio.get_running_loop()
    while True:
        start = loop.time()
        await asyncio.sleep(interval)
        overshoot = loop.time() - start - interval
        _lag_histogram.record(max(0.0, overshoot) * 1000.0)


def start_asyncio_metrics(interval: float = _LAG_PROBE_INTERVAL) -> None:
    """Bind the running loop and start the event-loop lag probe.

    Call from inside the event loop (e.g. the API lifespan startup). Idempotent:
    a second call rebinds the loop and leaves a live probe running.
    """
    global _loop, _lag_probe_task
    _loop = asyncio.get_running_loop()
    if _lag_probe_task is None or _lag_probe_task.done():
        _lag_probe_task = _loop.create_task(_lag_probe(interval))


async def stop_asyncio_metrics() -> None:
    """Cancel the lag probe and release the loop. Call on lifespan shutdown."""
    global _lag_probe_task, _loop
    task = _lag_probe_task
    _lag_probe_task = None
    _loop = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# endregion
