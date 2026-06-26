"""``build_chat_model`` bakes an OpenAI ``prompt_cache_key`` into ``model_kwargs``.

The key controls OpenAI prefix-cache routing: same-prefix requests pinned to one
cache node hit the cache more often. We default to a stable per-task key and let
callers (e.g. the audit agents) override it per run.
"""

import pytest

from doci.llm import build_chat_model

_DEFAULT_MODEL = "openai:gpt-5-nano-2025-08-07"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate from any DOCI_LLM_* / OPENAI_* in the ambient environment."""
    for k in list(__import__("os").environ):
        if k.startswith("DOCI_LLM_") or k.startswith("OPENAI_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_default_per_task_cache_key():
    model = build_chat_model("ANNOTATE_TEXT", default_model=_DEFAULT_MODEL)
    assert model.model_kwargs["prompt_cache_key"] == "doci:annotate_text"


def test_explicit_cache_key_overrides_default():
    model = build_chat_model(
        "AUDIT", default_model=_DEFAULT_MODEL, cache_key="doci:audit:run-123"
    )
    assert model.model_kwargs["prompt_cache_key"] == "doci:audit:run-123"


def test_empty_cache_key_disables_the_param(monkeypatch):
    """An empty key (escape hatch for strict gateways) omits the param entirely."""
    monkeypatch.setenv("DOCI_LLM_PARAMS", '{"prompt_cache_key": ""}')
    model = build_chat_model("EXTRACT_IMAGE", default_model=_DEFAULT_MODEL)
    assert "prompt_cache_key" not in model.model_kwargs


def test_extra_params_coexist_with_cache_key():
    """A model-specific param (reasoning_effort) survives the model_kwargs plumbing."""
    model = build_chat_model(
        "ANNOTATE_IMAGE",
        default_model=_DEFAULT_MODEL,
        default_params={"reasoning_effort": "low"},
    )
    assert model.reasoning_effort == "low"
    assert model.model_kwargs["prompt_cache_key"] == "doci:annotate_image"
