"""Shared construction of the service's long-lived clients.

Both the API lifespan (:mod:`doci.api.app`) and the taskiq worker startup need
the same Postgres / ObjStore / KV / Cache / MediaService wiring; centralising it
here keeps the two in sync.
"""

from dataclasses import dataclass, replace

from doci.cache import Cache, CacheMode
from doci.kvstore import KV, KVConfig
from doci.media import MediaConfig, MediaService
from doci.objstore import ObjStore
from doci.postgres import Postgres
from doci.results import WorkflowResultService
from doci.workflows import WorkflowExecutionService


@dataclass(frozen=True, slots=True)
class Clients:
    """The service's long-lived clients, built once and shared."""

    postgres: Postgres
    objstore: ObjStore
    kv: KV
    media: MediaService
    workflow_runs: WorkflowExecutionService
    workflow_results: WorkflowResultService


def build_clients() -> Clients:
    """Construct the shared clients from the environment."""
    pg = Postgres.from_env()
    obj = ObjStore.from_env()
    # All doci KV keys are namespaced under `doci:` (db comes from REDIS_DB/REDIS_URL,
    # default 0); db 1 is used by the TaskIQ broker (TASKIQ_BROKER_URL).
    kvcfg = KVConfig.from_env()
    if not kvcfg.key_prefix:
        kvcfg = replace(kvcfg, key_prefix="doci:")
    kv = KV(kvcfg)

    media_config = MediaConfig.from_env()
    media_cache = Cache(
        mode=CacheMode.KV_THEN_MEM,
        kv=kv,
        namespace="media:view",
        default_ttl=media_config.view_cache_ttl,
    )
    media = MediaService(
        postgres=pg, objstore=obj, cache=media_cache, config=media_config
    )
    workflow_runs = WorkflowExecutionService(postgres=pg)
    workflow_results = WorkflowResultService(postgres=pg)
    return Clients(
        postgres=pg,
        objstore=obj,
        kv=kv,
        media=media,
        workflow_runs=workflow_runs,
        workflow_results=workflow_results,
    )


async def close_clients(clients: Clients) -> None:
    """Release the shared clients (inverse of :func:`build_clients`)."""
    await clients.kv.aclose()
    clients.objstore.close()
    clients.postgres.close()
