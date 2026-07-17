"""Camada de carregamento e acesso à base de conhecimento (read-only, compute-only).

Os stores mutáveis (sugestões + auditoria) migraram para `..db` (ORM tenant-scoped);
aqui ficam só a KB Markdown/YAML e o grafo do ecossistema, dado de referência.
"""

from .ecosystem_graph import EcosystemGraph, EcosystemGraphError
from .governance_repository import GovernanceRepository
from .markdown_loader import KnowledgeDocument, KnowledgeSection, MarkdownLoader

__all__ = [
    "EcosystemGraph",
    "EcosystemGraphError",
    "KnowledgeDocument",
    "KnowledgeSection",
    "MarkdownLoader",
    "GovernanceRepository",
]
