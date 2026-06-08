"""Developer-facing task monitor (JSON, read-mostly) over Valkey.

taskiq has no event bus and its result backend can only look up *finished* tasks
by id, so a "running / scheduled / success / failed" board has to be recorded by
us. :class:`TaskMonitorMiddleware` writes a small lifecycle record per task into
the broker db (queued → running → success/failed), keyed for listing and
self-expiring after a TTL. :class:`TaskMonitor` reads it back, and
:func:`build_task_monitor_router` exposes it as JSON (list / detail / rerun).

Registered on the shared broker, the middleware records ``post_send`` on the
sender (API) and ``pre_execute`` / ``post_execute`` / ``on_error`` on the worker.
It must be added **before** the retry middleware so that a retried failure ends
as ``queued`` (the retry re-kick's ``post_send`` runs after ``on_error``) while a
terminal failure stays ``failed``.
"""

import json
import time
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any, cast

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query, Request, status
from taskiq.abc.broker import AsyncBroker
from taskiq.abc.middleware import TaskiqMiddleware
from taskiq.kicker import AsyncKicker
from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

# Lifecycle fields cleared when a task is (re)queued, so a requeued task looks fresh.
_RUNTIME_FIELDS = ("started_at", "finished_at", "error", "error_type", "execution_time")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskMonitor:
    """Read/write the per-task lifecycle records in Valkey.

    One Valkey hash per task (``{prefix}:task:{task_id}``) plus a sorted-set index
    (``{prefix}:index``, score = last-update epoch) for newest-first listing. Every
    key is stamped with ``ttl`` so abandoned records self-expire.
    """

    def __init__(self, url: str, *, prefix: str, ttl: int) -> None:
        self._url = url
        self._prefix = prefix
        self._ttl = ttl
        self._r: aioredis.Redis | None = None

    async def aopen(self) -> None:
        if self._r is None:  # idempotent: broker.startup() may fire more than once
            self._r = aioredis.Redis.from_url(self._url, decode_responses=True)

    async def aclose(self) -> None:
        if self._r is not None:
            await self._r.aclose()

    # region keys
    def _task_key(self, task_id: str) -> str:
        return f"{self._prefix}:task:{task_id}"

    @property
    def _index_key(self) -> str:
        return f"{self._prefix}:index"

    # endregion

    # region writes (used by the middleware)
    async def _touch(
        self, task_id: str, mapping: dict[str, str], *, clear: tuple[str, ...] = ()
    ) -> None:
        assert self._r is not None
        now = time.time()
        key = self._task_key(task_id)
        pipe = self._r.pipeline(transaction=False)
        if clear:
            pipe.hdel(key, *clear)
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, self._ttl)
        pipe.zadd(self._index_key, {task_id: now})
        pipe.expire(self._index_key, self._ttl)
        pipe.zremrangebyscore(self._index_key, "-inf", now - self._ttl)
        await pipe.execute()

    async def mark_queued(self, msg: TaskiqMessage) -> None:
        await self._touch(
            msg.task_id,
            {
                "task_id": msg.task_id,
                "task_name": msg.task_name,
                "state": "queued",
                "args": json.dumps(msg.args),
                "kwargs": json.dumps(msg.kwargs),
                "labels": json.dumps(msg.labels),
                "queued_at": _now_iso(),
            },
            clear=_RUNTIME_FIELDS,
        )

    async def mark_running(self, task_id: str) -> None:
        await self._touch(task_id, {"state": "running", "started_at": _now_iso()})

    async def mark_success(self, task_id: str, execution_time: float | None) -> None:
        await self._touch(
            task_id,
            {
                "state": "success",
                "finished_at": _now_iso(),
                "execution_time": json.dumps(execution_time),
            },
        )

    async def mark_failed(self, task_id: str, exception: BaseException) -> None:
        await self._touch(
            task_id,
            {
                "state": "failed",
                "finished_at": _now_iso(),
                "error": str(exception),
                "error_type": type(exception).__name__,
            },
        )

    # endregion

    # region reads (used by the router)
    @staticmethod
    def _parse(row: dict[str, str]) -> dict[str, Any]:
        rec = dict(row)
        for field in ("args", "kwargs", "labels", "execution_time"):
            if field in rec:
                try:
                    rec[field] = json.loads(rec[field])
                except ValueError, TypeError:
                    pass
        return rec

    async def list(
        self, *, state: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        assert self._r is not None
        # Bounded by the 3-day TTL; dev volume is small, so scan the index and filter.
        ids = await cast(
            "Awaitable[list[str]]", self._r.zrevrange(self._index_key, 0, 999)
        )
        if not ids:
            return []
        pipe = self._r.pipeline(transaction=False)
        for tid in ids:
            pipe.hgetall(self._task_key(tid))
        rows = await pipe.execute()
        out: list[dict[str, Any]] = []
        for tid, row in zip(ids, rows, strict=True):
            if not row:  # hash expired out from under the index
                await cast("Awaitable[int]", self._r.zrem(self._index_key, tid))
                continue
            if state is not None and row.get("state") != state:
                continue
            out.append(self._parse(row))
        return out[offset : offset + limit]

    async def get(self, task_id: str) -> dict[str, Any] | None:
        assert self._r is not None
        row = await cast("Awaitable[dict]", self._r.hgetall(self._task_key(task_id)))
        return self._parse(row) if row else None

    # endregion


class TaskMonitorMiddleware(TaskiqMiddleware):
    """Records each task's lifecycle into a :class:`TaskMonitor`.

    Owns the monitor's Valkey client (opened on broker startup, closed on
    shutdown). Failures are recorded in ``on_error``; ``post_execute`` only records
    success, so it never overwrites a retried failure that ``on_error`` left as
    ``queued`` (this middleware must be registered before the retry middleware).
    """

    def __init__(self, url: str, *, prefix: str, ttl: int) -> None:
        super().__init__()
        self._monitor = TaskMonitor(url, prefix=prefix, ttl=ttl)

    async def startup(self) -> None:
        await self._monitor.aopen()

    async def shutdown(self) -> None:
        await self._monitor.aclose()

    async def post_send(self, message: TaskiqMessage) -> None:
        await self._monitor.mark_queued(message)

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        await self._monitor.mark_running(message.task_id)
        return message

    async def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult[Any]
    ) -> None:
        if not result.is_err:
            await self._monitor.mark_success(message.task_id, result.execution_time)

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        await self._monitor.mark_failed(message.task_id, exception)


def build_task_monitor_router(
    broker: AsyncBroker, schedule_source: Any | None = None
) -> APIRouter:
    """JSON router for the developer task monitor.

    Resolves the :class:`TaskMonitor` reader from ``request.app.state.monitor``.
    """
    router = APIRouter(prefix="/tasks", tags=["tasks"])

    def _monitor(request: Request) -> TaskMonitor:
        return request.app.state.monitor

    @router.get("", summary="List tasks by state (newest first)")
    async def list_tasks(
        request: Request,
        state: str | None = Query(None, pattern="^(queued|running|success|failed)$"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        items = await _monitor(request).list(state=state, limit=limit, offset=offset)
        return {"items": items, "limit": limit, "offset": offset}

    # Declared before /{task_id} so "scheduled" isn't captured as a task id.
    @router.get("/scheduled", summary="List scheduled tasks")
    async def list_scheduled() -> dict[str, Any]:
        if schedule_source is None:
            return {"items": []}
        schedules = await schedule_source.get_schedules()
        return {"items": [s.model_dump(mode="json") for s in schedules]}

    @router.get("/{task_id}", summary="Task detail incl. result payload")
    async def get_task(request: Request, task_id: str) -> dict[str, Any]:
        rec = await _monitor(request).get(task_id)
        if rec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown task")
        if rec.get("state") in ("success", "failed"):
            rec["result"] = await _result_payload(broker, task_id)
        return rec

    @router.post("/{task_id}/retry", summary="Re-run a failed task")
    async def retry_task(request: Request, task_id: str) -> dict[str, Any]:
        rec = await _monitor(request).get(task_id)
        if rec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown task")
        if rec.get("state") != "failed":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"task is {rec.get('state')}, only failed tasks can be retried",
            )
        kicker: AsyncKicker[Any, Any] = AsyncKicker(
            task_name=rec["task_name"], broker=broker, labels=rec.get("labels") or {}
        ).with_task_id(task_id)
        await kicker.kiq(*(rec.get("args") or []), **(rec.get("kwargs") or {}))
        return {"task_id": task_id, "status": "requeued"}

    return router


async def _result_payload(broker: AsyncBroker, task_id: str) -> dict[str, Any] | None:
    """Full taskiq result for a finished task, or ``None`` if not stored."""
    try:
        res: TaskiqResult[Any] = await broker.result_backend.get_result(
            task_id, with_logs=True
        )
    except Exception:  # result missing/expired or backend error — best-effort
        return None
    return {
        "is_err": res.is_err,
        "return_value": res.return_value,
        "execution_time": res.execution_time,
        "error": str(res.error) if res.error is not None else None,
        "log": res.log,
    }
