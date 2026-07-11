"""Tools MCP para sugestões cross-repo (ORM tenant-scoped, async).

submit_suggestion        — agente abre uma sugestão para outro repo
list_suggestions         — listar com filtros (target_repo, status, etc.)
get_suggestion           — payload completo de uma sugestão pelo id
update_suggestion_status — muda o status, registrando histórico

A persistência é o ``SuggestionStore`` do ORM (`..db.store`), ligado ao pool do tenant
e passado por-request pelo servidor — as tools NÃO conhecem o SDK MCP nem o pool. O
``GovernanceRepository`` (KB read-only) continua vindo junto só para a resolução de
alias/deprecated do target_repo via ``EcosystemGraph`` (compute, síncrona).

Resolução automática de target_repo: se o agente passa um nome alias ou
deprecated_by, resolvemos para o canônico via EcosystemGraph e gravamos
em `target_repo_canonical`. O `target_repo` original fica preservado para
auditoria.
"""

from __future__ import annotations

from typing import get_args

from ..db.store import SuggestionStore, SuggestionStoreError
from ..knowledge.governance_repository import GovernanceRepository
from ..models.suggestion import (
    SuggestionCategory,
    SuggestionFilters,
    SuggestionSeverity,
    SuggestionStatus,
)
from ..utils.logger import get_logger
from ..utils.validators import (
    coerce_string_list,
    require_non_empty_string,
    safe_lower,
)

_log = get_logger(__name__)

_VALID_CATEGORIES = set(get_args(SuggestionCategory))
_VALID_SEVERITIES = set(get_args(SuggestionSeverity))
_VALID_STATUSES = set(get_args(SuggestionStatus))


class SuggestionsUnavailable(RuntimeError):
    """Sinaliza que o store está indisponível — convertido em payload de erro pelo server.

    Com o ORM tenant-scoped o store está sempre disponível dentro de uma sessão; esta
    exceção permanece como parte do contrato de erro do servidor (back-compat).
    """


def _resolve_canonical_target(repo: GovernanceRepository, target_repo: str) -> tuple[str | None, list[str]]:
    """Tenta resolver target_repo via EcosystemGraph (alias/deprecated_by).

    Devolve (canonical, notes). Se o grafo está indisponível ou o target não
    existe lá, devolve (None, ['target_repo não encontrado no grafo (aceito mesmo assim)']).
    """
    notes: list[str] = []
    if repo.ecosystem is None:
        return None, notes

    g = repo.ecosystem
    # Match direto?
    if g.graph.has_node(target_repo):
        node = g.graph.nodes[target_repo]
        # Se o nó está deprecated, redireciona para o canônico via deprecated_by.
        if node.get("status") == "deprecated":
            for _, dst, key in g.graph.out_edges(target_repo, keys=True):
                if key == "deprecated_by":
                    notes.append(f"target_repo '{target_repo}' está deprecado; redirecionado para '{dst}'.")
                    return dst, notes
        return target_repo, notes

    # Tenta resolver por alias.
    for node_id, attrs in g.graph.nodes(data=True):
        aliases = attrs.get("aliases") or []
        if target_repo in aliases:
            notes.append(f"target_repo '{target_repo}' é alias de '{node_id}' (canônico).")
            return node_id, notes

    notes.append(
        f"target_repo '{target_repo}' não encontrado no ecosystem.yaml — sugestão aceita "
        "mas o repo pode não estar modelado."
    )
    return None, notes


# ---------------------------------------------------------------------- #
# submit_suggestion                                                       #
# ---------------------------------------------------------------------- #
async def submit_suggestion(
    repo: GovernanceRepository,
    store: SuggestionStore,
    *,
    source_agent: str,
    target_repo: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    source_repo: str | None = None,
    related_files: list[str] | str | None = None,
    references: list[str] | str | None = None,
) -> dict:
    """Cria uma sugestão para outro serviço/repo."""
    require_non_empty_string(source_agent, "source_agent")
    require_non_empty_string(target_repo, "target_repo")
    require_non_empty_string(title, "title")
    require_non_empty_string(description, "description")

    cat_norm = safe_lower(category)
    if cat_norm not in _VALID_CATEGORIES:
        raise ValueError(f"category inválida: {category!r}. Opções: {sorted(_VALID_CATEGORIES)}")
    sev_norm = safe_lower(severity)
    if sev_norm not in _VALID_SEVERITIES:
        raise ValueError(f"severity inválida: {severity!r}. Opções: {sorted(_VALID_SEVERITIES)}")

    if len(title) > 200:
        raise ValueError("title muito longo (máx. 200 caracteres)")
    if len(description) > 8000:
        raise ValueError("description muito longa (máx. 8000 caracteres)")

    canonical, notes = _resolve_canonical_target(repo, target_repo)

    suggestion = await store.create(
        source_agent=source_agent.strip(),
        source_repo=source_repo.strip() if isinstance(source_repo, str) and source_repo.strip() else None,
        target_repo=target_repo.strip(),
        target_repo_canonical=canonical,
        category=cat_norm,  # type: ignore[arg-type]  # validado contra _VALID_CATEGORIES
        severity=sev_norm,  # type: ignore[arg-type]
        title=title.strip(),
        description=description.strip(),
        related_files=coerce_string_list(related_files),
        references=coerce_string_list(references),
    )

    return {
        "suggestion": suggestion.model_dump(),
        "notes": notes,
    }


# ---------------------------------------------------------------------- #
# list_suggestions                                                        #
# ---------------------------------------------------------------------- #
async def list_suggestions(
    repo: GovernanceRepository,
    store: SuggestionStore,
    *,
    target_repo: str | None = None,
    status: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    source_agent: str | None = None,
    limit: int | None = None,
) -> dict:
    """Lista sugestões aplicando filtros. Default: 20, ordem cronológica reversa."""
    filters_kwargs: dict = {}
    if target_repo:
        # Resolve alias/deprecated antes de filtrar.
        canonical, _ = _resolve_canonical_target(repo, target_repo)
        filters_kwargs["target_repo"] = canonical or target_repo
    if status:
        s = safe_lower(status)
        if s not in _VALID_STATUSES:
            raise ValueError(f"status inválido: {status!r}. Opções: {sorted(_VALID_STATUSES)}")
        filters_kwargs["status"] = s
    if category:
        c = safe_lower(category)
        if c not in _VALID_CATEGORIES:
            raise ValueError(f"category inválida: {category!r}. Opções: {sorted(_VALID_CATEGORIES)}")
        filters_kwargs["category"] = c
    if severity:
        sev = safe_lower(severity)
        if sev not in _VALID_SEVERITIES:
            raise ValueError(f"severity inválida: {severity!r}. Opções: {sorted(_VALID_SEVERITIES)}")
        filters_kwargs["severity"] = sev
    if source_agent:
        filters_kwargs["source_agent"] = source_agent
    if limit is not None:
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit deve ser inteiro positivo")
        filters_kwargs["limit"] = min(limit, 200)

    filters = SuggestionFilters(**filters_kwargs)
    items = await store.list(filters)
    return {
        "filters": filters.model_dump(),
        "total": len(items),
        "suggestions": [s.model_dump() for s in items],
    }


# ---------------------------------------------------------------------- #
# get_suggestion                                                          #
# ---------------------------------------------------------------------- #
async def get_suggestion(store: SuggestionStore, *, suggestion_id: str) -> dict:
    require_non_empty_string(suggestion_id, "suggestion_id")
    try:
        suggestion = await store.get(suggestion_id)
    except SuggestionStoreError as e:
        raise ValueError(str(e)) from e
    if suggestion is None:
        return {"found": False, "suggestion_id": suggestion_id}
    return {"found": True, "suggestion": suggestion.model_dump()}


# ---------------------------------------------------------------------- #
# update_suggestion_status                                                #
# ---------------------------------------------------------------------- #
async def update_suggestion_status(
    store: SuggestionStore,
    *,
    suggestion_id: str,
    new_status: str,
    note: str | None = None,
    by: str | None = None,
) -> dict:
    require_non_empty_string(suggestion_id, "suggestion_id")
    require_non_empty_string(new_status, "new_status")

    s = safe_lower(new_status)
    if s not in _VALID_STATUSES:
        raise ValueError(f"status inválido: {new_status!r}. Opções: {sorted(_VALID_STATUSES)}")

    try:
        suggestion = await store.update_status(
            suggestion_id,
            s,  # type: ignore[arg-type]
            note=note.strip() if isinstance(note, str) and note.strip() else None,
            by=by.strip() if isinstance(by, str) and by.strip() else None,
        )
    except SuggestionStoreError as e:
        raise ValueError(str(e)) from e
    return {"suggestion": suggestion.model_dump()}
