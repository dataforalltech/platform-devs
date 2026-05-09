"""Tools MCP de consulta ao grafo do ecossistema."""

from __future__ import annotations

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import require_non_empty_string, safe_lower

_GRAPH_UNAVAILABLE = {
    "error": "ecosystem_graph_unavailable",
    "details": (
        "ecosystem.yaml ausente ou inválido na knowledge-base. Crie/corrija o arquivo "
        "e reinicie o servidor para habilitar as tools de grafo."
    ),
}


def _require_graph(repo: GovernanceRepository):
    g = repo.ecosystem
    if g is None:
        raise GraphUnavailable()
    return g


class GraphUnavailable(RuntimeError):
    """Sinaliza que o grafo não está carregado — convertido em payload de erro pelo server."""


# --------------------------------------------------------------------- #
# query_ecosystem_graph                                                  #
# --------------------------------------------------------------------- #
def query_ecosystem_graph(
    repo: GovernanceRepository,
    query: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    relation: str | None = None,
    direction: str | None = None,
    node_id: str | None = None,
    filter_text: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Tool genérica que cobre 3 modos:

    - **list**: sem `node_id` → lista nós paginados, filtrando por `kind`, `status`, `filter_text`.
    - **neighbors**: com `node_id` → vizinhos diretos, filtrando por `relation`/`direction`.
    - **stats**: query=='stats' → métricas globais.
    """
    g = _require_graph(repo)

    q = safe_lower(query)
    if q == "stats":
        return {"query": "stats", "stats": g.stats()}

    direction_norm = (direction or "out").lower()
    if direction_norm not in ("out", "in", "both"):
        raise ValueError("direction deve ser 'out', 'in' ou 'both'")

    if node_id:
        neighbors = g.neighbors(node_id, relation=relation, direction=direction_norm)
        # Paginação em vizinhos
        total = len(neighbors)
        page = neighbors[offset: offset + limit]
        node = g.get_node(node_id)
        return {
            "query": "neighbors",
            "node": node,
            "direction": direction_norm,
            "relation_filter": relation,
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": page,
        }

    nodes = g.list_nodes(kind=kind, status=status)
    # Filtro de texto livre
    if filter_text:
        ft = filter_text.lower()
        nodes = [n for n in nodes if ft in str(n).lower()]
    total = len(nodes)
    page = nodes[offset: offset + limit]
    return {
        "query": "list",
        "filters": {"kind": kind, "status": status, "filter_text": filter_text},
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": page,
    }


# --------------------------------------------------------------------- #
# find_consumers_of                                                      #
# --------------------------------------------------------------------- #
def find_consumers_of(repo: GovernanceRepository, node_id: str) -> dict:
    """Quem consome o que `node_id` produz/provê.

    Resolve via contratos para serviços (provides_api/produces_event →
    consumes/consumes_event) e via uses_lib para libraries.
    """
    g = _require_graph(repo)
    require_non_empty_string(node_id, "node_id")

    if not g.graph.has_node(node_id):
        return {
            "node_id": node_id,
            "node": None,
            "total": 0,
            "consumers": [],
            "notes": [f"Nó '{node_id}' não existe no grafo."],
        }

    consumers = g.find_consumers_of(node_id)
    return {
        "node_id": node_id,
        "node": g.get_node(node_id),
        "total": len(consumers),
        "consumers": consumers,
    }


# --------------------------------------------------------------------- #
# find_dependencies_of                                                   #
# --------------------------------------------------------------------- #
def find_dependencies_of(
    repo: GovernanceRepository,
    node_id: str,
    include_transitive: bool = False,
    max_depth: int = 1,
) -> dict:
    """O que `node_id` depende.

    Por padrão retorna apenas dependências diretas (include_transitive=False).
    Use include_transitive=True para dependências transitivas (max_depth até 5).
    """
    g = _require_graph(repo)
    require_non_empty_string(node_id, "node_id")

    effective_depth = max_depth if include_transitive else 1
    if not isinstance(effective_depth, int) or effective_depth < 1:
        raise ValueError("max_depth deve ser inteiro >= 1")
    if effective_depth > 5:
        raise ValueError("max_depth máximo é 5")

    if not g.graph.has_node(node_id):
        return {
            "node_id": node_id,
            "node": None,
            "include_transitive": include_transitive,
            "total": 0,
            "dependencies": [],
            "notes": [f"Nó '{node_id}' não existe no grafo."],
        }

    deps = g.find_dependencies_of(node_id, max_depth=effective_depth)
    return {
        "node_id": node_id,
        "node": g.get_node(node_id),
        "include_transitive": include_transitive,
        "total": len(deps),
        "dependencies": deps,
    }


# --------------------------------------------------------------------- #
# get_service_metadata                                                   #
# --------------------------------------------------------------------- #
def get_service_metadata(repo: GovernanceRepository, node_id: str) -> dict:
    """Metadados completos de um nó: atributos + consumidores + dependências
    diretas + caminho canônico se houver redirecionamento (deprecated_by).
    """
    g = _require_graph(repo)
    require_non_empty_string(node_id, "node_id")

    node = g.get_node(node_id)
    if node is None:
        return {
            "node_id": node_id,
            "found": False,
            "notes": [f"Nó '{node_id}' não existe no grafo."],
        }

    # Detecta redirecionamento canônico (status=deprecated + aresta deprecated_by).
    canonical_redirect: str | None = None
    if node.get("status") == "deprecated":
        for edge in g.neighbors(node_id, relation="deprecated_by", direction="out"):
            canonical_redirect = edge["to"]
            break

    direct_deps = g.find_dependencies_of(node_id, max_depth=1)
    consumers = g.find_consumers_of(node_id)

    notes: list[str] = []
    if canonical_redirect:
        notes.append(
            f"⚠ Este nó está deprecado. Use '{canonical_redirect}' (canônico)."
        )

    return {
        "node_id": node_id,
        "found": True,
        "node": node,
        "canonical_redirect": canonical_redirect,
        "direct_dependencies": direct_deps,
        "consumers": consumers,
        "notes": notes,
    }
