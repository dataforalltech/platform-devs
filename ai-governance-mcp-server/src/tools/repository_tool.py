"""Tool de busca textual na knowledge-base."""

from __future__ import annotations

from ..config.settings import get_settings
from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import require_non_empty_string


def search_governance_knowledge(
    repo: GovernanceRepository,
    query: str,
    limit: int | None = None,
) -> dict:
    """Busca textual simples por palavra-chave.

    O ranking atual é heurístico (frequência + bonus de heading); a interface
    devolve trechos prontos para serem consumidos por um agente. Quando
    quisermos evoluir para busca semântica, basta trocar a implementação em
    GovernanceRepository.search — esta tool fica intacta.
    """
    require_non_empty_string(query, "query")
    settings = get_settings()

    if limit is None:
        effective_limit = settings.search_default_limit
    else:
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit deve ser inteiro positivo")
        effective_limit = min(limit, settings.search_max_limit)

    raw_hits = repo.search(
        query=query,
        limit=effective_limit,
        snippet_length=settings.search_snippet_length,
    )

    hits = [
        {
            "source": h["source"],
            "section": h["section"],
            "snippet": h["snippet"],
            "score": h["score"],
            "related_rules": _related_rules_for(h["source"]),
        }
        for h in raw_hits
    ]

    return {
        "query": query,
        "total": len(hits),
        "hits": hits,
    }


_RELATED_RULES = {
    "AGENTS.md": ["política universal", "proibições explícitas"],
    "frontend.md": ["frontend é consumidor de contrato", "sem regra de negócio"],
    "backend.md": ["contrato é autoridade", "observabilidade obrigatória"],
    "database.md": ["migration reversível", "sem DROP em código de app"],
    "integrations.md": ["timeout + retry", "fallback explícito"],
    "fallback.md": ["fallback silencioso é proibido"],
    "contracts.md": ["versionamento obrigatório em breaking change"],
    "security.md": ["sem bypass de auth", "logs sem PII bruta"],
    "observability.md": ["log + métrica + alerta"],
    "testing.md": ["bugfix sem regressão é incompleto"],
    "forbidden-actions.md": ["lista canônica de proibições"],
    "final-response-format.md": ["resposta final obrigatória do agente"],
    "infrastructure.md": ["secrets fora do repositório"],
}


def _related_rules_for(source: str) -> list[str]:
    return list(_RELATED_RULES.get(source, []))
