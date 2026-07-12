"""LLM rate-limiting middleware for the audit deep agents.

A langchain/deepagents ``AgentMiddleware`` that gates every model call through a
shared :class:`RedisTokenBucket`. ``awrap_model_call`` is the right layer because
it sees the outgoing ``request.messages`` — it can count tokens and gate on the
*token* budget, unlike a model-level ``rate_limiter=`` hook which is blind to
request size and can only pace request *count*.

Accounting reserves the pre-call input estimate, then reconciles against the
model's reported ``usage_metadata.total_tokens`` so the bucket tracks true
consumption (no fixed worst-case output reserve wasting the budget).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages.utils import count_tokens_approximately

from doci.llm.ratelimit import RedisTokenBucket, resolve_rate_limit

if TYPE_CHECKING:
    from doci.kvstore.client import KV

_log = logging.getLogger(__name__)


def _actual_total_tokens(response: Any) -> int | None:
    """Pull the model's reported total token count out of a model response."""
    messages = getattr(response, "result", None)
    if messages is None:
        messages = [response]  # a bare AIMessage may be returned by inner middleware
    for msg in reversed(list(messages)):
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            total = usage.get("total_tokens")
            if total:
                return int(total)
    return None


class TokenBucketMiddleware(AgentMiddleware):
    """Gate each model call on a shared token bucket; reconcile actual usage after."""

    def __init__(self, bucket: RedisTokenBucket) -> None:
        super().__init__()
        self._bucket = bucket

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = list(request.messages)
        if request.system_message is not None:
            messages = [request.system_message, *messages]
        estimate = count_tokens_approximately(messages, tools=request.tools)

        await self._bucket.acquire(estimate)
        response = await handler(request)

        actual = _actual_total_tokens(response)
        if actual is not None:
            await self._bucket.adjust(actual - estimate)
        return response


def build_rate_limit_middleware(
    kv: "KV",
    task: str,
    *,
    tpm: int | None = None,
    window_s: int | None = None,
) -> list[AgentMiddleware]:
    """Middleware list gating ``task``'s model calls; empty when the limiter is off.

    ``tpm``/``window_s`` default from the ``DOCI_LLM_<TASK>_<FIELD>`` env chain and
    can be overridden here. A resolved ``tpm <= 0`` disables the limiter (returns
    ``[]``), so agents run unthrottled.
    """
    tpm, window_s = resolve_rate_limit(task, tpm=tpm, window_s=window_s)
    if tpm <= 0:
        return []
    bucket = RedisTokenBucket(
        kv, tpm=tpm, window_s=window_s, key=f"ratelimit:llm:{task.lower()}"
    )
    return [TokenBucketMiddleware(bucket)]


__all__ = ["TokenBucketMiddleware", "build_rate_limit_middleware"]
