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
) -> BaseChatModel:
    """Build a provider-agnostic LangChain chat model for a named ``task`` profile.

    ``default_max_tokens`` / ``default_params`` are the per-task code defaults
    (env ``DOCI_LLM_*`` still overrides) — e.g. a reasoning-model vision task ships
    a larger token budget and ``{"reasoning_effort": "minimal"}``.
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
    kwargs.update(config.extra_params)  # model-specific params win
    return init_chat_model(
        config.model, **kwargs
    )  # "provider:model" => provider inferred


__all__ = ["LLMConfig", "build_chat_model"]
