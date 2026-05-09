"""Repositório de governança — fachada de leitura sobre a base de conhecimento.

A camada de tools nunca toca em arquivos diretamente; sempre passa por aqui.
Isto permite trocar a fonte (filesystem → vector DB → API) sem mexer nas tools.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..utils.logger import get_logger
from .ecosystem_graph import EcosystemGraph, EcosystemGraphError
from .markdown_loader import KnowledgeDocument, KnowledgeSection, MarkdownLoader
from .suggestion_store import SuggestionStore

_log = get_logger(__name__)

# Mapeamento dos arquivos canônicos da knowledge-base para tópicos.
_LAYER_FILE_MAP = {
    "frontend": "frontend.md",
    "backend": "backend.md",
    "database": "database.md",
    "integrations": "integrations.md",
    "infrastructure": "infrastructure.md",
    "security": "security.md",
    "observability": "observability.md",
    "testing": "testing.md",
}

_TOPIC_FILE_MAP = {
    "fallback": "fallback.md",
    "contracts": "contracts.md",
    "forbidden": "forbidden-actions.md",
    "final-response": "final-response-format.md",
    "agents": "AGENTS.md",
}

# Stopwords PT/EN para não poluir o ranking de busca textual.
_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "para", "por", "com", "sem", "que", "se", "ao",
    "à", "às", "aos", "e", "ou", "mas", "como", "quando", "onde", "qual",
    "quais", "ser", "estar", "ter", "haver", "the", "an", "of", "to",
    "in", "on", "at", "by", "for", "with", "and", "or", "but", "is", "are",
    "be", "been", "was", "were", "this", "that", "these", "those",
}

_TOKEN_RE = re.compile(r"[\wÀ-ÿ\-]+", re.UNICODE)


@dataclass
class _IndexedSection:
    document: KnowledgeDocument
    section: KnowledgeSection
    tokens: Counter[str]


class GovernanceRepository:
    """Acesso somente-leitura à knowledge-base.

    Carrega documentos no construtor; expõe consultas por arquivo, camada e busca.
    Não expõe paths absolutos para fora — apenas o `name` do arquivo.
    """

    def __init__(
        self,
        kb_path: Path,
        suggestions_path: Path | None = None,
    ) -> None:
        self.kb_path = kb_path
        self._suggestions_path = suggestions_path or (kb_path / "suggestions")
        self._documents: dict[str, KnowledgeDocument] = {}
        self._index: list[_IndexedSection] = []
        self._ecosystem: EcosystemGraph | None = None
        self._suggestions: SuggestionStore | None = None
        self._load()
        self._load_graph()
        self._load_suggestions()

    def _load(self) -> None:
        loader = MarkdownLoader(self.kb_path)
        docs = loader.load_all()
        if not docs:
            _log.warning(
                "Nenhum arquivo .md encontrado na knowledge-base",
                extra={"extras": {"kb_path": str(self.kb_path)}},
            )
        for doc in docs:
            self._documents[doc.name] = doc
            for section in doc.sections:
                tokens = self._tokenize(section.heading + " " + section.content)
                self._index.append(_IndexedSection(doc, section, tokens))
        _log.info(
            "knowledge-base carregada",
            extra={"extras": {"docs": len(self._documents), "sections": len(self._index)}},
        )

    def _load_graph(self) -> None:
        """Carrega ecosystem.yaml se existir. Ausência não é erro fatal —
        apenas degrada graciosamente as tools de grafo (que retornam erro tipado)."""
        yaml_path = self.kb_path / "ecosystem.yaml"
        if not yaml_path.exists():
            _log.warning(
                "ecosystem.yaml ausente — graph tools ficarão degradadas",
                extra={"extras": {"path": str(yaml_path)}},
            )
            return
        try:
            self._ecosystem = EcosystemGraph(yaml_path)
        except EcosystemGraphError as e:
            _log.error(
                "ecosystem.yaml inválido — graph tools desabilitadas",
                extra={"extras": {"error": str(e)}},
            )
            self._ecosystem = None

    @property
    def ecosystem(self) -> EcosystemGraph | None:
        """Acesso somente-leitura ao grafo. None se ausente/inválido."""
        return self._ecosystem

    def _load_suggestions(self) -> None:
        """Inicializa o SuggestionStore. Cria a pasta se ausente."""
        try:
            self._suggestions = SuggestionStore(self._suggestions_path)
        except OSError as e:
            _log.error(
                "suggestion_store_unavailable",
                extra={"extras": {"error": str(e), "path": str(self._suggestions_path)}},
            )
            self._suggestions = None

    @property
    def suggestions(self) -> SuggestionStore | None:
        """Acesso ao store de sugestões cross-repo. None se filesystem falhou."""
        return self._suggestions

    @staticmethod
    def _tokenize(text: str) -> Counter[str]:
        tokens = [
            tok.lower()
            for tok in _TOKEN_RE.findall(text)
            if len(tok) > 2 and tok.lower() not in _STOPWORDS
        ]
        return Counter(tokens)

    # ------------------------------------------------------------------ #
    # Acesso direto                                                       #
    # ------------------------------------------------------------------ #
    def list_documents(self) -> list[str]:
        return sorted(self._documents.keys())

    def get_document(self, name: str) -> KnowledgeDocument | None:
        return self._documents.get(name)

    def get_layer_document(self, layer: str) -> KnowledgeDocument | None:
        filename = _LAYER_FILE_MAP.get(layer)
        if not filename:
            return None
        return self._documents.get(filename)

    def get_topic_document(self, topic: str) -> KnowledgeDocument | None:
        filename = _TOPIC_FILE_MAP.get(topic)
        if not filename:
            return None
        return self._documents.get(filename)

    # ------------------------------------------------------------------ #
    # Busca textual simples                                               #
    # ------------------------------------------------------------------ #
    def search(
        self,
        query: str,
        limit: int = 5,
        snippet_length: int = 400,
    ) -> list[dict]:
        """Score = soma das frequências dos tokens da query encontrados na seção.

        Retorna lista de dicts (não Pydantic — o caller decide o shape final).
        """
        if not query or not query.strip():
            return []

        query_tokens = [
            tok.lower()
            for tok in _TOKEN_RE.findall(query)
            if len(tok) > 2 and tok.lower() not in _STOPWORDS
        ]
        if not query_tokens:
            return []

        scored: list[tuple[float, _IndexedSection]] = []
        for entry in self._index:
            score = 0.0
            matched = 0
            for tok in query_tokens:
                count = entry.tokens.get(tok, 0)
                if count:
                    matched += 1
                    score += count
            if matched == 0:
                continue
            # Bonus por casar mais tokens distintos (precision sobre recall).
            score *= 1.0 + 0.5 * matched
            # Bonus pequeno se um token aparece no heading (mais relevante).
            heading_lower = entry.section.heading.lower()
            for tok in query_tokens:
                if tok in heading_lower:
                    score *= 1.25
                    break
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict] = []
        for score, entry in scored[:limit]:
            content = entry.section.content
            snippet = content[:snippet_length].strip()
            if len(content) > snippet_length:
                snippet += " …"
            results.append(
                {
                    "source": entry.document.name,
                    "section": entry.section.heading,
                    "snippet": snippet,
                    "score": round(score, 3),
                }
            )
        return results
