"""The token-bucket middleware gates model calls and reconciles actual usage."""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from doci.agents.ratelimit import TokenBucketMiddleware, build_rate_limit_middleware


class _FakeBucket:
    def __init__(self) -> None:
        self.acquired: list[int] = []
        self.adjusted: list[int] = []

    async def acquire(self, tokens: int) -> None:
        self.acquired.append(tokens)

    async def adjust(self, delta: int) -> None:
        self.adjusted.append(delta)


def _request(messages, system=None, tools=()):
    return SimpleNamespace(
        messages=list(messages), system_message=system, tools=list(tools)
    )


def _resp(*messages):
    return SimpleNamespace(result=list(messages))


def test_acquires_estimate_then_reconciles_actual():
    bucket = _FakeBucket()
    mw = TokenBucketMiddleware(bucket)
    req = _request([HumanMessage("hello world")], system=SystemMessage("sys"))

    ai = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": 900,
            "output_tokens": 100,
            "total_tokens": 1000,
        },
    )

    async def handler(request):
        # gate must run before the model call
        assert bucket.acquired and not bucket.adjusted
        return _resp(ai)

    out = asyncio.run(mw.awrap_model_call(req, handler))

    assert out.result[0] is ai  # response passed through untouched
    assert len(bucket.acquired) == 1
    est = bucket.acquired[0]
    assert est > 0
    # reconciled to the true total: adjust(actual_total - reserved_estimate)
    assert bucket.adjusted == [1000 - est]


def test_no_usage_metadata_skips_reconcile():
    bucket = _FakeBucket()
    mw = TokenBucketMiddleware(bucket)
    req = _request([HumanMessage("hi")])

    async def handler(request):
        return _resp(AIMessage(content="no usage"))  # usage_metadata is None

    asyncio.run(mw.awrap_model_call(req, handler))
    assert len(bucket.acquired) == 1
    assert bucket.adjusted == []  # nothing to reconcile


def test_estimate_counts_system_and_messages():
    bucket = _FakeBucket()
    mw = TokenBucketMiddleware(bucket)
    long_sys = SystemMessage("word " * 500)
    req = _request([HumanMessage("hi")], system=long_sys)

    async def handler(request):
        return _resp(AIMessage(content="ok"))

    asyncio.run(mw.awrap_model_call(req, handler))
    with_sys = bucket.acquired[0]

    bucket2 = _FakeBucket()
    mw2 = TokenBucketMiddleware(bucket2)
    req2 = _request([HumanMessage("hi")])  # no system message
    asyncio.run(mw2.awrap_model_call(req2, handler))
    assert with_sys > bucket2.acquired[0]  # system prompt is included in the estimate


# region factory
class _FakeKV:
    def script(self, lua):
        async def _run(*, keys=(), args=()):
            return 0

        return _run


def test_factory_disabled_when_tpm_zero():
    assert build_rate_limit_middleware(_FakeKV(), "AUDIT", tpm=0) == []


def test_factory_builds_one_middleware_when_enabled():
    mw = build_rate_limit_middleware(_FakeKV(), "AUDIT", tpm=500_000, window_s=60)
    assert len(mw) == 1
    assert isinstance(mw[0], TokenBucketMiddleware)


# endregion
