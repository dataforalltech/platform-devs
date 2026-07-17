"""Modelos Pydantic para respostas das tools de grafo."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """Um nó do grafo do ecossistema."""

    id: str
    kind: str
    status: str | None = None
    description: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Uma aresta do grafo."""

    src: str = Field(alias="from")
    dst: str = Field(alias="to")
    relation: str
    extras: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class ConsumerEntry(BaseModel):
    """Linha de 'quem consome o quê' devolvida por find_consumers_of."""

    id: str
    kind: str
    status: str | None = None
    via: list[dict[str, str]] = Field(
        default_factory=list,
        description="Lista de {relation, target} mostrando como o consumidor chega.",
    )


class DependencyEntry(BaseModel):
    """Dependência devolvida por find_dependencies_of (com profundidade do BFS)."""

    id: str
    kind: str
    status: str | None = None
    depth: int
    via_relation: str | None = None
    via_target: str | None = None


class GraphQueryResponse(BaseModel):
    """Resposta genérica de query_ecosystem_graph."""

    query: str
    total: int
    results: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GraphStats(BaseModel):
    """Métricas resumidas do grafo carregado."""

    total_nodes: int
    total_edges: int
    nodes_by_kind: dict[str, int]
    edges_by_relation: dict[str, int]
    source: str
