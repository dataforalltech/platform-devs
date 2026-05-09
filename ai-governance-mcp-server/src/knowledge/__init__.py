"""Camada de carregamento e acesso à base de conhecimento."""

from .ecosystem_graph import EcosystemGraph, EcosystemGraphError
from .governance_repository import GovernanceRepository
from .markdown_loader import KnowledgeDocument, KnowledgeSection, MarkdownLoader
from .suggestion_store import SuggestionStore, SuggestionStoreError

__all__ = [
    "EcosystemGraph",
    "EcosystemGraphError",
    "KnowledgeDocument",
    "KnowledgeSection",
    "MarkdownLoader",
    "GovernanceRepository",
    "SuggestionStore",
    "SuggestionStoreError",
]
