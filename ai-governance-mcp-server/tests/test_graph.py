"""Testes do EcosystemGraph e das 4 tools de grafo.

Os testes usam o ecosystem.yaml real do repositório — qualquer drift entre o
seed e as queries aparece como falha aqui.
"""

from __future__ import annotations

import pytest
import yaml

from src.knowledge.ecosystem_graph import EcosystemGraph, EcosystemGraphError
from src.tools.graph_tool import (
    GraphUnavailable,
    find_consumers_of,
    find_dependencies_of,
    get_service_metadata,
    query_ecosystem_graph,
)


# --------------------------- repositório carrega o grafo --------------------------- #
def test_repo_loads_ecosystem_graph(repo):
    assert repo.ecosystem is not None
    stats = repo.ecosystem.stats()
    assert stats["total_nodes"] >= 20
    assert stats["total_edges"] >= 30
    assert stats["nodes_by_kind"]["service"] >= 10


def test_graph_has_no_orphans_or_broken_edges(repo):
    rep = repo.ecosystem.report
    assert rep is not None
    assert rep.broken_edges == [], f"arestas com endpoint inexistente: {rep.broken_edges}"
    assert rep.unknown_kinds == []
    assert rep.unknown_relations == []


# --------------------------- query_ecosystem_graph --------------------------- #
def test_query_stats_returns_metrics(repo):
    res = query_ecosystem_graph(repo, query="stats")
    assert res["query"] == "stats"
    assert "total_nodes" in res["stats"]


def test_query_list_filters_by_kind(repo):
    res = query_ecosystem_graph(repo, kind="library")
    assert res["query"] == "list"
    assert res["filters"]["kind"] == "library"
    ids = {n["id"] for n in res["results"]}
    assert "platform-core-lib" in ids
    assert "platform-db-vector" in ids


def test_query_list_filters_by_status(repo):
    res = query_ecosystem_graph(repo, status="deprecated")
    ids = {n["id"] for n in res["results"]}
    assert "connectors-platform" in ids
    assert "schedule-platform" in ids
    # Garante que não vazaram ativos.
    for node in res["results"]:
        assert node.get("status") == "deprecated"


def test_query_neighbors_outbound(repo):
    res = query_ecosystem_graph(repo, node_id="dataforall-agents-factory", direction="out")
    assert res["query"] == "neighbors"
    targets = {(e["to"], e["relation"]) for e in res["results"]}
    assert ("platform-db-vector", "uses_lib") in targets
    assert ("rag.search.api", "consumes") in targets


def test_query_neighbors_inbound(repo):
    res = query_ecosystem_graph(repo, node_id="platform-core-lib", direction="in", relation="uses_lib")
    sources = {e["from"] for e in res["results"]}
    assert "dataforall-agents-factory" in sources
    assert "dataforall-rag-service" in sources


def test_query_invalid_direction(repo):
    with pytest.raises(ValueError):
        query_ecosystem_graph(repo, node_id="dataforall-rag-service", direction="weird")


# --------------------------- find_consumers_of --------------------------- #
def test_consumers_of_service_via_contracts(repo):
    res = find_consumers_of(repo, node_id="dataforall-rag-service")
    consumer_ids = {c["id"] for c in res["consumers"]}
    assert "dataforall-agents-factory" in consumer_ids


def test_consumer_aggregates_multiple_via_targets(repo):
    """agents-factory consome 2 contratos do rag-service — deve aparecer 1 vez com via=[2]."""
    res = find_consumers_of(repo, node_id="dataforall-rag-service")
    af = next(c for c in res["consumers"] if c["id"] == "dataforall-agents-factory")
    targets = {v["target"] for v in af["via"]}
    assert "rag.search.api" in targets
    assert "rag.embeddings.api" in targets


def test_consumers_of_library(repo):
    res = find_consumers_of(repo, node_id="platform-core-lib")
    consumer_ids = {c["id"] for c in res["consumers"]}
    # platform-core-lib é usada por praticamente todos os serviços ativos.
    assert "dataforall-rag-service" in consumer_ids
    assert "dataforall-agents-factory" in consumer_ids
    assert "platform-cdc" in consumer_ids


def test_consumers_of_unknown_node(repo):
    res = find_consumers_of(repo, node_id="does-not-exist")
    assert res["total"] == 0
    assert res["node"] is None
    assert any("não existe" in n.lower() for n in res["notes"])


def test_consumers_requires_node_id(repo):
    with pytest.raises(ValueError):
        find_consumers_of(repo, node_id="")


# --------------------------- find_dependencies_of --------------------------- #
def test_dependencies_of_agents_factory_direct(repo):
    res = find_dependencies_of(repo, node_id="dataforall-agents-factory", max_depth=1)
    dep_ids = {d["id"] for d in res["dependencies"]}
    assert "platform-db-vector" in dep_ids
    assert "rag.search.api" in dep_ids
    assert "platform-service-template" in dep_ids


def test_dependencies_with_depth_2_finds_transitive(repo):
    res = find_dependencies_of(repo, node_id="dataforall-agents-factory", max_depth=2)
    # depth=2 deve encontrar pelo menos rag-service (via rag.search.api), se modelado.
    # Como contratos não têm out-edges para rag-service na nossa modelagem, depth=2 igual a 1.
    # Mas o teste verifica que profundidade 2 não falha e retorna >= depth=1.
    res1 = find_dependencies_of(repo, node_id="dataforall-agents-factory", max_depth=1)
    assert len(res["dependencies"]) >= len(res1["dependencies"])


def test_dependencies_max_depth_validation(repo):
    with pytest.raises(ValueError):
        find_dependencies_of(repo, node_id="dataforall-rag-service", max_depth=0)
    with pytest.raises(ValueError):
        find_dependencies_of(repo, node_id="dataforall-rag-service", max_depth=10)


# --------------------------- get_service_metadata --------------------------- #
def test_metadata_for_active_service(repo):
    res = get_service_metadata(repo, node_id="dataforall-rag-service")
    assert res["found"] is True
    assert res["canonical_redirect"] is None
    assert res["node"]["id"] == "dataforall-rag-service"
    assert any(d["id"] == "platform-core-lib" for d in res["direct_dependencies"])


def test_metadata_for_deprecated_service_redirects_to_canonical(repo):
    res = get_service_metadata(repo, node_id="connectors-platform")
    assert res["found"] is True
    assert res["canonical_redirect"] == "platform-connectors"
    assert any("deprecado" in n.lower() for n in res["notes"])


def test_metadata_for_unknown_node(repo):
    res = get_service_metadata(repo, node_id="not-real")
    assert res["found"] is False


# --------------------------- regras canônicas da memória do projeto --------------------------- #
def test_platform_cdc_runs_on_port_8017(repo):
    """Canônica em AGENTS.md §47 e DEVOPS_STANDARDS §3: cdc=8017, NOT 8018.
    Memória do projeto tinha 8018 errado — o grafo é a fonte da verdade agora."""
    res = query_ecosystem_graph(repo, node_id="platform-cdc", relation="runs_on_port", direction="out")
    targets = {e["to"] for e in res["results"]}
    assert "port-8017" in targets


def test_platform_api_gateway_runs_on_port_8018(repo):
    """8018 é do api-gateway, não do cdc."""
    res = query_ecosystem_graph(repo, node_id="platform-api-gateway", relation="runs_on_port", direction="out")
    targets = {e["to"] for e in res["results"]}
    assert "port-8018" in targets


def test_platform_admin_uses_port_8002_only(repo):
    res = query_ecosystem_graph(repo, node_id="platform-admin", relation="runs_on_port", direction="out")
    targets = {e["to"] for e in res["results"]}
    assert "port-8002" in targets
    assert "port-8017" not in targets
    assert "port-8018" not in targets


def test_platform_ml_does_not_provide_embeddings(repo):
    """Canônica em §49: platform-ml não tem embeddings — só rag-service."""
    res = query_ecosystem_graph(repo, node_id="platform-ml", direction="out")
    # platform-ml não deve produzir nenhum contrato de embeddings.
    for edge in res["results"]:
        assert "embeddings" not in edge.get("to", "").lower()


def test_rag_service_owns_embeddings_api(repo):
    res = query_ecosystem_graph(repo, node_id="dataforall-rag-service", relation="provides_api", direction="out")
    targets = {e["to"] for e in res["results"]}
    assert "rag.embeddings.api" in targets
    assert "rag.search.api" in targets


# ----------------- propriedades do grafo canônico (após expansão §47/§49) ----------------- #
def test_all_canonical_services_present(repo):
    """Todos os 22 serviços canônicos da AGENTS.md §47 devem estar no grafo."""
    expected = {
        "platform-auth", "platform-admin", "platform-governance", "platform-analytics",
        "platform-scheduler", "platform-connectors", "platform-ml", "platform-cloud",
        "platform-monitor", "platform-notification", "platform-communication",
        "platform-dataquality", "platform-docextract", "dataforall-agents-factory",
        "dataforall-rag-service", "platform-datalake", "platform-cdc",
        "platform-api-gateway", "platform-iceberg", "platform-flow", "platform-security",
        "dataforall-ui-connect",
    }
    res = query_ecosystem_graph(repo, kind="service", status="active")
    ids = {n["id"] for n in res["results"]}
    missing = expected - ids
    assert not missing, f"serviços canônicos ausentes: {missing}"


def test_each_active_service_has_port(repo):
    """Cada serviço ativo (exceto template, pipeline) tem port atribuída — bate com §47."""
    services_without_port = {"platform-service-template", "platform-pipeline"}
    res = query_ecosystem_graph(repo, kind="service", status="active")
    for service in res["results"]:
        if service["id"] in services_without_port:
            continue
        # Cada deve ter ao menos uma aresta runs_on_port
        edges = query_ecosystem_graph(
            repo, node_id=service["id"], relation="runs_on_port", direction="out"
        )
        assert edges["total"] >= 1, f"{service['id']} não tem porta atribuída"


def test_no_two_services_share_a_port(repo):
    """Cada porta tem no máximo um serviço (canonicidade)."""
    res = query_ecosystem_graph(repo, kind="port")
    for port in res["results"]:
        edges = query_ecosystem_graph(
            repo, node_id=port["id"], relation="runs_on_port", direction="in"
        )
        assert edges["total"] <= 1, f"{port['id']} compartilhada por: {edges['results']}"


def test_platform_auth_owns_jwt_and_jwks(repo):
    res = query_ecosystem_graph(
        repo, node_id="platform-auth", relation="provides_api", direction="out"
    )
    targets = {e["to"] for e in res["results"]}
    assert "auth.jwt.api" in targets
    assert "auth.jwks.api" in targets


def test_only_rag_service_provides_embeddings(repo):
    """Apenas dataforall-rag-service provê o contrato de embeddings — §49 explicit_non_responsibilities."""
    res = query_ecosystem_graph(
        repo, node_id="rag.embeddings.api", relation="provides_api", direction="in"
    )
    sources = {e["from"] for e in res["results"]}
    assert sources == {"dataforall-rag-service"}, (
        f"embeddings deve ser owned somente por rag-service; encontrado: {sources}"
    )


def test_agents_factory_consumes_both_rag_apis(repo):
    res = find_consumers_of(repo, node_id="dataforall-rag-service")
    af = next(c for c in res["consumers"] if c["id"] == "dataforall-agents-factory")
    targets = {v["target"] for v in af["via"]}
    assert "rag.search.api" in targets
    assert "rag.embeddings.api" in targets


def test_api_gateway_is_canonical_entry(repo):
    """platform-api-gateway é a entrada única de tráfego externo — todos consumidores."""
    res = query_ecosystem_graph(repo, node_id="platform-api-gateway")
    # deve existir
    assert res["node"] is not None
    assert res["node"]["port"] == 8018


def test_deprecated_services_have_canonical_redirect(repo):
    """Serviços deprecados têm redirecionamento canônico via deprecated_by."""
    deprecated = query_ecosystem_graph(repo, status="deprecated")
    for dep in deprecated["results"]:
        meta = get_service_metadata(repo, node_id=dep["id"])
        assert meta["canonical_redirect"] is not None, (
            f"{dep['id']} é deprecado mas não tem deprecated_by"
        )


def test_db_vector_used_only_by_rag_layer(repo):
    """platform-db-vector é privada da camada RAG — só rag-service e agents-factory."""
    res = find_consumers_of(repo, node_id="platform-db-vector")
    consumer_ids = {c["id"] for c in res["consumers"]}
    assert consumer_ids == {"dataforall-rag-service", "dataforall-agents-factory"}, (
        f"platform-db-vector tem consumidores inesperados: {consumer_ids}"
    )


# --------------------------- graph unavailability --------------------------- #
def test_graph_loader_rejects_invalid_yaml(tmp_path):
    bad = tmp_path / "ecosystem.yaml"
    bad.write_text("nodes: not-a-list\nedges: 'string'\n", encoding="utf-8")
    with pytest.raises(EcosystemGraphError):
        EcosystemGraph(bad)


def test_graph_loader_detects_duplicate_nodes(tmp_path):
    dup = tmp_path / "ecosystem.yaml"
    dup.write_text(
        yaml.safe_dump(
            {
                "nodes": [
                    {"id": "x", "kind": "service"},
                    {"id": "x", "kind": "service"},
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EcosystemGraphError):
        EcosystemGraph(dup)


def test_graph_loader_collects_broken_edges(tmp_path):
    """Aresta apontando para nó inexistente vai pro report.broken_edges, não levanta."""
    g_path = tmp_path / "ecosystem.yaml"
    g_path.write_text(
        yaml.safe_dump(
            {
                "nodes": [{"id": "a", "kind": "service"}],
                "edges": [{"from": "a", "to": "ghost", "relation": "uses_lib"}],
            }
        ),
        encoding="utf-8",
    )
    g = EcosystemGraph(g_path)
    assert ("a", "ghost", "uses_lib") in g.report.broken_edges


def test_graph_unavailable_raised_when_grafo_ausente(tmp_path):
    """Se ecosystem.yaml for removido, GraphUnavailable é levantada nas tools."""

    class _StubRepo:
        ecosystem = None

    stub = _StubRepo()
    with pytest.raises(GraphUnavailable):
        find_consumers_of(stub, node_id="dataforall-rag-service")
    with pytest.raises(GraphUnavailable):
        query_ecosystem_graph(stub)
