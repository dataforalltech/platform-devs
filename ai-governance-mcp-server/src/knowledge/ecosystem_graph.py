"""EcosystemGraph — grafo in-memory dos repositórios/serviços/contratos.

Backend: networkx.MultiDiGraph (multi-aresta dirigida — duas entidades podem
ter mais de uma relação, ex.: agents-factory `consumes` e `uses_lib`).

Fonte: arquivo YAML em knowledge-base/ecosystem.yaml.

Esta camada é a única que conhece networkx. As tools em src/tools/graph_tool.py
chamam apenas a API pública desta classe — assim, quando trocarmos para Neo4j
ou outro backend, só esta classe muda.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from ..utils.logger import get_logger

_log = get_logger(__name__)


# --------------------------------------------------------------------- #
# Constantes — relações canônicas e categorias                          #
# --------------------------------------------------------------------- #

VALID_KINDS = {
    "repository",
    "service",
    "library",
    "contract",
    "team",
    "port",
}

VALID_RELATIONS = {
    "depends_on",
    "consumes",
    "produces",
    "owns",
    "deprecated_by",
    "replaces",
    "runs_on_port",
    "uses_lib",
    "provides_api",
    "consumes_event",
    "produces_event",
    "based_on",
}

# Relações que representam "dependência" para a tool find_dependencies_of.
DEPENDENCY_RELATIONS = {
    "depends_on",
    "uses_lib",
    "consumes",
    "consumes_event",
    "based_on",
}

# Relações que representam "produção" para a tool find_consumers_of.
PRODUCTION_RELATIONS = {
    "provides_api",
    "produces_event",
    "produces",
}


# --------------------------------------------------------------------- #
# Erros tipados                                                          #
# --------------------------------------------------------------------- #

class EcosystemGraphError(ValueError):
    """Erro de carregamento ou validação do grafo."""


@dataclass
class GraphValidationReport:
    """Resultado da validação estrutural pós-load."""

    total_nodes: int
    total_edges: int
    orphan_nodes: list[str]  # nós sem nenhuma aresta
    unknown_kinds: list[str]
    unknown_relations: list[str]
    broken_edges: list[tuple[str, str, str]]  # (from, to, relation) com endpoint inexistente


# --------------------------------------------------------------------- #
# Classe principal                                                       #
# --------------------------------------------------------------------- #

class EcosystemGraph:
    """Carrega o YAML para um MultiDiGraph e expõe consultas tipadas."""

    def __init__(self, yaml_path: Path) -> None:
        self.yaml_path = yaml_path
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self.report: GraphValidationReport | None = None
        self._load()

    # ------------------------------------------------------------------ #
    # Carregamento                                                        #
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        if not self.yaml_path.exists():
            raise EcosystemGraphError(
                f"ecosystem.yaml não encontrado em {self.yaml_path}. "
                "Verifique GOVERNANCE_KB_PATH ou crie o arquivo."
            )
        try:
            data = yaml.safe_load(self.yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise EcosystemGraphError(f"YAML inválido em {self.yaml_path}: {e}") from e

        if not isinstance(data, dict):
            raise EcosystemGraphError("ecosystem.yaml deve ter root como mapping")

        nodes = data.get("nodes") or []
        edges = data.get("edges") or []

        unknown_kinds: list[str] = []
        for node in nodes:
            self._add_node(node, unknown_kinds)

        unknown_relations: list[str] = []
        broken_edges: list[tuple[str, str, str]] = []
        for edge in edges:
            self._add_edge(edge, unknown_relations, broken_edges)

        orphans = [n for n, deg in self.graph.degree() if deg == 0]
        self.report = GraphValidationReport(
            total_nodes=self.graph.number_of_nodes(),
            total_edges=self.graph.number_of_edges(),
            orphan_nodes=sorted(orphans),
            unknown_kinds=sorted(set(unknown_kinds)),
            unknown_relations=sorted(set(unknown_relations)),
            broken_edges=broken_edges,
        )
        _log.info(
            "ecosystem_graph_loaded",
            extra={
                "extras": {
                    "nodes": self.report.total_nodes,
                    "edges": self.report.total_edges,
                    "orphans": len(self.report.orphan_nodes),
                    "unknown_kinds": self.report.unknown_kinds,
                    "broken_edges": len(self.report.broken_edges),
                }
            },
        )

    def _add_node(self, payload: dict, unknown_kinds: list[str]) -> None:
        if not isinstance(payload, dict):
            raise EcosystemGraphError(f"node deve ser mapping; recebido {type(payload).__name__}")
        node_id = payload.get("id")
        kind = payload.get("kind")
        if not isinstance(node_id, str) or not node_id.strip():
            raise EcosystemGraphError(f"node sem id válido: {payload!r}")
        if not isinstance(kind, str) or not kind.strip():
            raise EcosystemGraphError(f"node {node_id!r} sem kind")
        if kind not in VALID_KINDS:
            unknown_kinds.append(kind)
        if self.graph.has_node(node_id):
            raise EcosystemGraphError(f"node duplicado: {node_id!r}")
        attrs = {k: v for k, v in payload.items() if k != "id"}
        self.graph.add_node(node_id, **attrs)

    def _add_edge(
        self,
        payload: dict,
        unknown_relations: list[str],
        broken: list[tuple[str, str, str]],
    ) -> None:
        if not isinstance(payload, dict):
            raise EcosystemGraphError(f"edge deve ser mapping; recebido {type(payload).__name__}")
        src = payload.get("from")
        dst = payload.get("to")
        rel = payload.get("relation")
        if not all(isinstance(x, str) and x.strip() for x in (src, dst, rel)):
            raise EcosystemGraphError(f"edge inválido: {payload!r}")
        if rel not in VALID_RELATIONS:
            unknown_relations.append(rel)
        if not self.graph.has_node(src) or not self.graph.has_node(dst):
            broken.append((src, dst, rel))
            return
        attrs = {k: v for k, v in payload.items() if k not in {"from", "to"}}
        self.graph.add_edge(src, dst, key=rel, **attrs)

    # ------------------------------------------------------------------ #
    # Consultas — todas devolvem dict serializável                        #
    # ------------------------------------------------------------------ #
    def get_node(self, node_id: str) -> dict | None:
        if not self.graph.has_node(node_id):
            return None
        return self._render_node(node_id)

    def list_nodes(
        self,
        kind: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        out: list[dict] = []
        for node_id, data in self.graph.nodes(data=True):
            if kind and data.get("kind") != kind:
                continue
            if status and data.get("status") != status:
                continue
            out.append(self._render_node(node_id))
        return sorted(out, key=lambda n: n["id"])

    def neighbors(
        self,
        node_id: str,
        relation: str | None = None,
        direction: str = "out",
    ) -> list[dict]:
        """Vizinhos diretos. direction: out | in | both."""
        if not self.graph.has_node(node_id):
            return []
        if direction not in ("out", "in", "both"):
            raise EcosystemGraphError(f"direction inválida: {direction!r}")

        results: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        if direction in ("out", "both"):
            for _, dst, key, attrs in self.graph.out_edges(node_id, keys=True, data=True):
                if relation and key != relation:
                    continue
                triple = (node_id, key, dst)
                if triple in seen:
                    continue
                seen.add(triple)
                results.append(self._render_edge(node_id, dst, key, attrs))

        if direction in ("in", "both"):
            for src, _, key, attrs in self.graph.in_edges(node_id, keys=True, data=True):
                if relation and key != relation:
                    continue
                triple = (src, key, node_id)
                if triple in seen:
                    continue
                seen.add(triple)
                results.append(self._render_edge(src, node_id, key, attrs))

        return results

    def find_consumers_of(self, node_id: str) -> list[dict]:
        """Quem consome o que `node_id` produz/provê.

        Para um service: pega todos os contratos que ele `provides_api`/`produces_event`,
        depois encontra quem `consumes`/`consumes_event` cada contrato. Se o mesmo
        consumidor casa por mais de um contrato, agregamos todos em `via`.
        Para um contrato: encontra direto.
        Para uma library: lista quem `uses_lib`.
        """
        if not self.graph.has_node(node_id):
            return []

        kind = self.graph.nodes[node_id].get("kind")
        # consumer_id -> {"id": ..., ..., "via": [{"relation": ..., "target": ...}, ...]}
        consumers: dict[str, dict] = {}

        def _add(consumer_id: str, relation: str, target: str) -> None:
            if consumer_id == node_id:
                return
            entry = consumers.get(consumer_id)
            if entry is None:
                entry = self._render_node(consumer_id)
                entry["via"] = []
                consumers[consumer_id] = entry
            entry["via"].append({"relation": relation, "target": target})

        if kind == "contract":
            for src, _, key in self.graph.in_edges(node_id, keys=True):
                if key in {"consumes", "consumes_event"}:
                    _add(src, key, node_id)
        else:
            # Contratos que esse node provê.
            for _, contract_id, key in self.graph.out_edges(node_id, keys=True):
                if key in PRODUCTION_RELATIONS:
                    for src, _, in_key in self.graph.in_edges(contract_id, keys=True):
                        if in_key in {"consumes", "consumes_event"}:
                            _add(src, in_key, contract_id)

        # Quem usa o node como lib.
        if kind == "library":
            for src, _, key in self.graph.in_edges(node_id, keys=True):
                if key == "uses_lib":
                    _add(src, key, node_id)

        return sorted(consumers.values(), key=lambda n: n["id"])

    def find_dependencies_of(
        self,
        node_id: str,
        max_depth: int = 1,
    ) -> list[dict]:
        """O que `node_id` depende (uses_lib, consumes, consumes_event, depends_on).

        max_depth=1 → vizinhos diretos (default).
        max_depth=2..N → faz BFS limitada em arestas de dependência.
        """
        if not self.graph.has_node(node_id):
            return []
        if max_depth < 1:
            raise EcosystemGraphError("max_depth deve ser >= 1")

        visited: set[str] = {node_id}
        results: dict[str, dict] = {}
        queue: deque[tuple[str, int, str | None, str | None]] = deque(
            [(node_id, 0, None, None)]
        )

        while queue:
            current, depth, via_rel, via_src = queue.popleft()
            if depth >= max_depth:
                continue
            for _, dst, key in self.graph.out_edges(current, keys=True):
                if key not in DEPENDENCY_RELATIONS:
                    continue
                if dst not in visited:
                    visited.add(dst)
                    results[dst] = self._render_node(
                        dst, via_relation=key, via_target=current, depth=depth + 1
                    )
                    queue.append((dst, depth + 1, key, current))

        return sorted(results.values(), key=lambda n: (n.get("depth", 0), n["id"]))

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        """Caminho mais curto (em número de arestas) ignorando direção da relação.

        Útil para perguntas tipo 'como X chega em Y'.
        """
        if not self.graph.has_node(src) or not self.graph.has_node(dst):
            return None
        try:
            return nx.shortest_path(self.graph.to_undirected(as_view=True), src, dst)
        except nx.NetworkXNoPath:
            return None

    # ------------------------------------------------------------------ #
    # Serialização interna                                                #
    # ------------------------------------------------------------------ #
    def _render_node(self, node_id: str, **extras: Any) -> dict:
        attrs = dict(self.graph.nodes[node_id])
        out = {"id": node_id, **attrs}
        out.update(extras)
        return out

    def _render_edge(self, src: str, dst: str, relation: str, attrs: dict) -> dict:
        return {
            "from": src,
            "to": dst,
            "relation": relation,
            **{k: v for k, v in attrs.items() if k not in {"from", "to", "relation"}},
        }

    # ------------------------------------------------------------------ #
    # Stats                                                                #
    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            kind = data.get("kind", "unknown")
            kinds[kind] = kinds.get(kind, 0) + 1
        relations: dict[str, int] = {}
        for _, _, key in self.graph.edges(keys=True):
            relations[key] = relations.get(key, 0) + 1
        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "nodes_by_kind": kinds,
            "edges_by_relation": relations,
            "source": str(self.yaml_path.name),
        }
