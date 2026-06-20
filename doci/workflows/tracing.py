"""Tracing helpers for threading observability through nested graph invocations.

The OpenInference LangChain instrumentor builds its span tree from LangChain's
``Run`` objects and their ``parent_run_id`` — carried through the ``callbacks`` in
the ``RunnableConfig`` — not from the ambient OTel context. So a nested
``.ainvoke`` that builds a *fresh* config (dropping the parent's ``callbacks``)
starts a detached run tree and its spans flatten onto the root. :func:`child_config`
derives the child config from the parent so the run tree (and our semantic
labels) carry over.
"""

from typing import Any
from collections.abc import Sequence

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs


def child_config(
    parent: RunnableConfig | None,
    *,
    thread_id: str,
    run_name: str | None = None,
    tags: Sequence[str] | None = None,
    metadata: dict[str, Any] | None = None,
    recursion_limit: int | None = None,
) -> RunnableConfig:
    """Derive a child ``RunnableConfig`` from ``parent`` for a nested invocation.

    Preserves the parent's ``callbacks`` (so OpenInference nests the child's spans
    under the parent run, instead of flattening them onto the LangGraph root) and
    its ``tags``/``metadata``, while overriding ``thread_id`` and layering on the
    optional ``run_name``/``tags``/``metadata``/``recursion_limit`` for this child.
    ``merge_configs`` unions tags, merges metadata + configurable, and combines
    callbacks; ``run_name`` and ``recursion_limit`` take the override.
    """
    overrides: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    if run_name:
        overrides["run_name"] = run_name
    if tags:
        overrides["tags"] = list(tags)
    if metadata:
        overrides["metadata"] = metadata
    if recursion_limit is not None:
        overrides["recursion_limit"] = recursion_limit
    return merge_configs(parent, overrides)