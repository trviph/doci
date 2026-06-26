"""Provider-agnostic LLM client construction (LangChain ``init_chat_model``)."""

from collections.abc import Mapping
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from doci.llm.config import LLMConfig


def build_chat_model(
    task: str,
    *,
    default_model: str,
    default_max_tokens: int = 4096,
    default_params: Mapping[str, Any] | None = None,
    cache_key: str | None = None,
) -> BaseChatModel:
    """Build a provider-agnostic LangChain chat model for a named ``task`` profile.

    ``default_max_tokens`` / ``default_params`` are the per-task code defaults
    (env ``DOCI_LLM_*`` still overrides) — e.g. a reasoning-model vision task ships
    a larger token budget and ``{"reasoning_effort": "minimal"}``.

    OpenAI prefix-cache routing: a ``prompt_cache_key`` is baked into the request
    so same-prefix calls (the static system prompt + reused dossier catalog) are
    pinned to one cache node, lifting the cache-hit rate. Defaults to a stable
    per-task key (``doci:<task>``); pass ``cache_key`` for finer grouping (e.g. an
    audit run id). Set it empty (``DOCI_LLM[_<TASK>]_PARAMS={"prompt_cache_key":""}``)
    to disable — useful if a custom gateway rejects the param.
    """
    config = LLMConfig.from_env(
        task,
        default_model=default_model,
        default_max_tokens=default_max_tokens,
        default_params=default_params,
    )
    kwargs: dict[str, Any] = {
        "max_tokens": config.max_tokens,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    extra = dict(config.extra_params)  # model-specific params win
    model_kwargs: dict[str, Any] = dict(extra.pop("model_kwargs", {}))
    # An explicit cache_key wins; else an env-supplied one; else the per-task
    # default. An empty/None key disables routing (omit the param entirely).
    key = cache_key if cache_key is not None else extra.pop("prompt_cache_key", None)
    if key is None:
        key = f"doci:{task.lower()}"
    if key:
        model_kwargs["prompt_cache_key"] = key
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs
    kwargs.update(extra)
    return init_chat_model(
        config.model, **kwargs
    )  # "provider:model" => provider inferred


__all__ = ["LLMConfig", "build_chat_model"]
