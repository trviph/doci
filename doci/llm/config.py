"""Per-task LLM configuration.

Each task (an activity or agent) configures its own model independently. Env
resolution is per-field, three levels (cf. argos):

    DOCI_LLM_<TASK>_<FIELD>  ->  DOCI_LLM_<FIELD>  ->  per-task code default

so each task picks its own MODEL/TEMPERATURE/PARAMS while shared credentials
(e.g. a common gateway BASE_URL/API_KEY) are set once under DOCI_LLM_*.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Resolved settings for one task's chat model."""

    model: str  # "provider:model" for init_chat_model
    base_url: str | None = None  # custom/OpenAI-compatible/local endpoint
    api_key: str | None = None  # else provider-native env (OPENAI_API_KEY, ...)
    max_tokens: int = 4096
    timeout: int = 60
    max_retries: int = 2
    temperature: float | None = None  # opt-in; omitted when None
    extra_params: Mapping[str, Any] = field(
        default_factory=dict
    )  # model-specific kwargs

    @classmethod
    def from_env(cls, task: str, *, default_model: str) -> "LLMConfig":
        """Resolve config for ``task`` (e.g. "EXTRACT_PDF_GRAPHIC", "SUMMARIZE").

        Per field: ``DOCI_LLM_<TASK>_<FIELD>`` -> ``DOCI_LLM_<FIELD>`` -> default.
        """
        t = task.upper()

        def _e(name: str, default: str | None = None) -> str | None:
            return (
                os.getenv(f"DOCI_LLM_{t}_{name}")
                or os.getenv(f"DOCI_LLM_{name}")
                or default
            )

        temp = _e("TEMPERATURE")
        return cls(
            model=_e("MODEL", default_model) or default_model,
            base_url=_e("BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            api_key=_e("API_KEY"),  # None => langchain reads OPENAI_API_KEY/etc.
            max_tokens=int(_e("MAX_TOKENS", "4096")),
            timeout=int(_e("TIMEOUT", "60")),
            max_retries=int(_e("MAX_RETRIES", "2")),
            temperature=float(temp) if temp is not None else None,
            extra_params=json.loads(_e("PARAMS", "{}")),
        )
