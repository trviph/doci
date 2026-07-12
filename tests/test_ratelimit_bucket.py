"""Distributed token-bucket rate limiter: config resolution + acquire/adjust loop.

The Lua atomicity is exercised against a real Valkey in the e2e verification; here
we drive the client-side loop with a fake ``kv.script`` callable (no Redis).
"""

import asyncio

import pytest

from doci.llm.ratelimit import (
    DEFAULT_RATE_LIMIT_TPM,
    DEFAULT_RATE_LIMIT_WINDOW_S,
    RedisTokenBucket,
    resolve_rate_limit,
)


class _FakeScript:
    """Records calls; returns queued values (last value repeats when drained)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.returns: list = [0]

    async def __call__(self, *, keys, args):
        self.calls.append({"keys": list(keys), "args": list(args)})
        return self.returns[min(len(self.calls) - 1, len(self.returns) - 1)]


class _FakeKV:
    def __init__(self) -> None:
        self.scripts: list[_FakeScript] = []

    def script(self, lua: str) -> _FakeScript:
        s = _FakeScript()
        self.scripts.append(s)
        return s


def _bucket(kv, *, tpm=1000, window_s=60, key="ratelimit:llm:audit"):
    return RedisTokenBucket(kv, tpm=tpm, window_s=window_s, key=key)


# region config resolution
def test_resolve_defaults(monkeypatch):
    for var in (
        "DOCI_LLM_RATE_LIMIT_TPM",
        "DOCI_LLM_RATE_LIMIT_WINDOW_S",
        "DOCI_LLM_AUDIT_RATE_LIMIT_TPM",
        "DOCI_LLM_AUDIT_RATE_LIMIT_WINDOW_S",
    ):
        monkeypatch.delenv(var, raising=False)
    tpm, window = resolve_rate_limit("AUDIT")
    assert tpm == DEFAULT_RATE_LIMIT_TPM == 500_000
    assert window == DEFAULT_RATE_LIMIT_WINDOW_S == 60


def test_resolve_shared_env_override(monkeypatch):
    monkeypatch.setenv("DOCI_LLM_RATE_LIMIT_TPM", "120000")
    monkeypatch.setenv("DOCI_LLM_RATE_LIMIT_WINDOW_S", "30")
    monkeypatch.delenv("DOCI_LLM_AUDIT_RATE_LIMIT_TPM", raising=False)
    assert resolve_rate_limit("AUDIT") == (120_000, 30)


def test_resolve_per_task_beats_shared(monkeypatch):
    monkeypatch.setenv("DOCI_LLM_RATE_LIMIT_TPM", "120000")
    monkeypatch.setenv("DOCI_LLM_AUDIT_RATE_LIMIT_TPM", "50000")
    tpm, _ = resolve_rate_limit("AUDIT")
    assert tpm == 50_000


def test_resolve_explicit_beats_env(monkeypatch):
    monkeypatch.setenv("DOCI_LLM_RATE_LIMIT_TPM", "120000")
    tpm, window = resolve_rate_limit("AUDIT", tpm=7777, window_s=15)
    assert (tpm, window) == (7777, 15)


# endregion


# region acquire / adjust loop
def test_acquire_waits_then_proceeds(monkeypatch):
    kv = _FakeKV()
    bucket = _bucket(kv)
    acquire_script = kv.scripts[0]
    acquire_script.returns = [500, 0]  # wait 500ms, then allowed

    slept: list[float] = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    asyncio.run(bucket.acquire(200))

    assert len(acquire_script.calls) == 2  # polled twice
    assert len(slept) == 1  # slept once between polls
    assert 0 < slept[0] <= bucket._max_sleep_s + 1


def test_acquire_clamps_to_capacity(monkeypatch, caplog):
    kv = _FakeKV()
    bucket = _bucket(kv, tpm=1000)
    kv.scripts[0].returns = [0]  # immediately allowed

    asyncio.run(bucket.acquire(5000))  # asks more than capacity (1000)

    # requested arg (index 2: rate, capacity, requested, ttl) is clamped to capacity
    assert int(float(kv.scripts[0].calls[0]["args"][2])) == 1000
    assert any("capacity" in r.message.lower() for r in caplog.records)


def test_acquire_zero_wait_no_sleep(monkeypatch):
    kv = _FakeKV()
    bucket = _bucket(kv)
    kv.scripts[0].returns = [0]
    slept = []
    monkeypatch.setattr(asyncio, "sleep", lambda s: slept.append(s))
    # sleep is replaced with a non-coroutine; ensure it is never awaited/called
    asyncio.run(bucket.acquire(10))
    assert slept == []


def test_adjust_zero_is_noop():
    kv = _FakeKV()
    bucket = _bucket(kv)
    adjust_script = kv.scripts[1]
    asyncio.run(bucket.adjust(0))
    assert adjust_script.calls == []


def test_adjust_applies_signed_delta():
    kv = _FakeKV()
    bucket = _bucket(kv)
    adjust_script = kv.scripts[1]
    asyncio.run(bucket.adjust(-320))
    assert len(adjust_script.calls) == 1
    assert int(float(adjust_script.calls[0]["args"][2])) == -320


# endregion
