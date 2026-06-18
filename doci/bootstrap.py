"""Shared construction of the service's long-lived clients.

Both the API lifespan (:mod:`doci.api.app`) and the taskiq worker startup need
the same Postgres / ObjStore / KV / Cache / MediaService wiring; centralising it
here keeps the two in sync.
"""

from dataclasses import dataclass, replace

from doci.cache import Cache, CacheMode
from doci.documents import DocumentService
from doci.kvstore import KV, KVConfig
from doci.media import MediaConfig, MediaService
from doci.objstore import ObjStore
from doci.postgres import Postgres
from doci.results import WorkflowResultService
from doci.userdata.dossiers import DossierDefService
from doci.userdata.documents import DocumentDefService
from doci.userdata.knowledge import KnowledgeService
from doci.userdata.rules import AgentRuleService
from doci.workflows import WorkflowExecutionService


@dataclass(frozen=True, slots=True)
class Clients:
    """The service's long-lived clients, built once and shared."""

    postgres: Postgres
    objstore: ObjStore
    kv: KV
    media: MediaService
    documents: DocumentService
    workflow_runs: WorkflowExecutionService
    workflow_results: WorkflowResultService
    userdata_dossier_defs: DossierDefService
    userdata_document_defs: DocumentDefService
    userdata_agent_rules: AgentRuleService
    userdata_knowledge: KnowledgeService


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
    documents = DocumentService(postgres=pg, media=media, config=media_config)
    workflow_runs = WorkflowExecutionService(postgres=pg)
    workflow_results = WorkflowResultService(postgres=pg)
    userdata_dossier_defs = DossierDefService(postgres=pg)
    userdata_document_defs = DocumentDefService(postgres=pg)
    userdata_agent_rules = AgentRuleService(postgres=pg)
    userdata_knowledge = KnowledgeService(postgres=pg)
    return Clients(
        postgres=pg,
        objstore=obj,
        kv=kv,
        media=media,
        documents=documents,
        workflow_runs=workflow_runs,
        workflow_results=workflow_results,
        userdata_dossier_defs=userdata_dossier_defs,
        userdata_document_defs=userdata_document_defs,
        userdata_agent_rules=userdata_agent_rules,
        userdata_knowledge=userdata_knowledge,
    )


async def close_clients(clients: Clients) -> None:
    """Release the shared clients (inverse of :func:`build_clients`)."""
    await clients.kv.aclose()
    clients.objstore.close()
    clients.postgres.close()
