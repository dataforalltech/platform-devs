"""Testes da Fase 1 — derivação determinística, store e Discovery API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from platform_catalog.app import app
from platform_catalog.derive import derive_operation, provider_id
from platform_catalog.registry import CatalogStore

CATALOG = Path(__file__).resolve().parents[1] / "catalog"


# --- derivação --------------------------------------------------------------
def test_derive_write_high_risk_deploy():
    op_id, spec, meta = derive_operation("deploy-mcp-server", "deploy", "write")
    assert op_id == "delivery.deploy"
    assert spec.domain == "delivery"
    assert spec.authz.value == "write"
    assert "deploy" in spec.risk.effects
    assert spec.risk.blast_radius.value == "environment"
    assert spec.risk.default_level.value == "high"
    assert spec.risk.approval_required.value == "N2"  # HIGH → N2 (ADR-005)
    assert spec.contract.execution.idempotent is False  # write não é idempotente
    assert "github" in spec.risk.requires  # dependência do deploy-mcp


def test_derive_read_is_low_and_idempotent():
    op_id, spec, meta = derive_operation("services-mcp-server", "list_services", "read")
    assert op_id == "infra.list_services"
    assert spec.authz.value == "read"
    assert spec.risk.effects == ["read"]
    assert spec.risk.default_level.value == "low"
    assert spec.risk.approval_required.value == "none"
    assert spec.contract.execution.idempotent is True  # read é idempotente


def test_provider_id_strips_server_suffix():
    assert provider_id("deploy-mcp-server") == "deploy-mcp"


# --- seed materializado -----------------------------------------------------
def test_seed_present_and_counts():
    """O índice tem de bater com o catálogo EM DISCO — não com um número fixo.

    A versão anterior travava `{operations: 288, tools: 298, providers: 20}`. O
    catálogo cresceu para 307/317/23 em 2026-07-21 e o índice não foi regravado;
    como o teste afirmava o número velho, ele passava verde sobre um índice
    defasado por três semanas. Um teste que fixa a contagem não protege a
    consistência: protege a desatualização.

    Guarda de drift equivalente para uso fora da suíte:
    `python scripts/reindex_platform_catalog.py --check`.
    """
    idx = json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))
    em_disco = {
        "operations": len(list((CATALOG / "operations").glob("*.yaml"))),
        "tools": len(list((CATALOG / "tools").glob("*.yaml"))),
        "providers": len(list((CATALOG / "providers").glob("*.yaml"))),
    }
    assert idx["counts"] == em_disco
    assert all(quantidade > 0 for quantidade in em_disco.values())
    # portabilidade: há Operations com >1 Tool binding (ex.: product-owner × product-manager)
    assert idx["portability"]["operations_with_multiple_tools"] >= 1
    assert "product.generate_feature_spec" in idx["portability"]["examples"]


# --- store / Discovery ------------------------------------------------------
@pytest.fixture(scope="module")
def store():
    return CatalogStore().load()


def test_store_loads(store):
    st = store.stats()
    assert (
        st["owned_operations"] == 307 and st["external_operations"] == 3
    )  # +admin/auth federados
    assert len(store.operations) == 310
    assert len(store.tools) == 320  # 317 owned + 3 external
    assert len(store.providers) == 25  # 23 owned + admin + auth


def test_get_and_queries(store):
    assert store.get("delivery.deploy") is not None
    assert store.get("nope.nope") is None
    assert store.list_by_domain("delivery")
    assert store.find_by_effect("deploy")
    assert store.find_by_risk("high")
    assert store.find_by_resource("service")
    assert any("deploy" in o["metadata"]["uid"] for o in store.search("deploy"))


def test_resolve_and_portability(store):
    tools = store.list_tools_for("product.generate_feature_spec")
    assert len(tools) == 2  # PO + PM → 2 providers
    providers = {t["spec"]["provider_id"] for t in tools}
    assert providers == {"product-owner-mcp", "product-manager-mcp"}
    chosen = store.resolve_tool("product.generate_feature_spec")
    assert (
        chosen is not None
        and chosen["spec"]["operation_id"] == "product.generate_feature_spec"
    )


# --- Discovery API HTTP -----------------------------------------------------
@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_api_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_api_list_by_domain(client):
    r = client.get("/v1/operations", params={"domain": "testing"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    assert all(o["domain"] == "testing" for o in body["operations"])


def test_api_get_operation_and_404(client):
    assert client.get("/v1/operations/delivery.deploy").status_code == 200
    assert client.get("/v1/operations/does.not.exist").status_code == 404


def test_api_tools_and_resolve(client):
    r = client.get("/v1/operations/product.generate_feature_spec/tools")
    assert r.status_code == 200 and r.json()["count"] == 2
    r2 = client.get("/v1/operations/product.generate_feature_spec/resolve")
    assert r2.status_code == 200 and "provider_id" in r2.json()


def test_api_stats(client):
    s = client.get("/v1/stats").json()
    assert s["owned_operations"] == 307 and s["external_operations"] == 3
    assert s["operations"] == 310
    assert "delivery" in s["operations_by_domain"]
    assert s["write_operations"] > 0
