"""Knowledge: natural-language org reference material an agent consults."""

from doci.userdata.knowledge.models import Knowledge
from doci.userdata.knowledge.router import KnowledgeModel, build_knowledge_router
from doci.userdata.knowledge.service import KnowledgeService

__all__ = [
    "Knowledge",
    "KnowledgeService",
    "KnowledgeModel",
    "build_knowledge_router",
]
