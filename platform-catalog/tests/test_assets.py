"""Fase 5 (ADR-014) — assets no catálogo: critérios de sucesso + validação de relação."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from platform_catalog.app import app
from platform_catalog.registry import CatalogStore
from platform_catalog.validate import validate_catalog


@pytest.fixture(scope="module")
def store():
    return CatalogStore().load()


def test_assets_loaded_by_kind(store):
    kinds = {}
    for a in store.assets.values():
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    assert kinds.get("Runbook") == 6
    assert kinds.get("Persona") == 8
    assert kinds.get("Prompt") == 8
    assert kinds.get("Policy") == 8
    assert kinds.get("ADR", 0) >= 9


# critério 1 — Runbook executa por Operation, não por Tool
def test_runbook_references_operations(store):
    rb = store.get_asset("runbook.deploy_service")
    assert rb is not None
    tasks = rb["spec"]["tasks"]
    assert all(t["resolved"] and t["operation_id"] in store.operations for t in tasks)
    assert {"verb": "uses", "target": "delivery.deploy"} in rb["relations"]


# critério 2 — Persona tem allow-list catalogada
def test_persona_has_allowlist(store):
    p = store.get_asset("persona.devops")
    assert p is not None
    allow = p["spec"]["allow_list"]
    assert "deploy" in allow["allowed_effects"] and allow["max_blast"] == "environment"


# critério 3 — Prompt deixa de ser texto solto (é asset com ref + metadados)
def test_prompt_is_catalogued(store):
    pr = store.get_asset("prompt.backend")
    assert pr is not None and pr["spec"]["content_ref"].endswith("backend.md")
    assert {"verb": "part-of", "target": "persona.backend"} in pr["relations"]


# critério 4 — ADR consultável (por operação, via consulta reversa)
def test_adr_and_reverse_query(store):
    assert store.get_asset("adr.009") is not None
    assert "runbook.deploy_service" in store.assets_for_operation("delivery.deploy")


# relation validation (§8) — pós Fase 1.1, platform_health resolve via admin/auth federados
def test_validation_clean_and_platform_health_resolved(store):
    assert validate_catalog(store) == []          # §1-§8 limpo
    ph = store.get_asset("runbook.platform_health")
    assert ph is not None
    # admin/auth federados (external) → platform_health resolve 100%
    assert all(t["resolved"] and t["operation_id"] in store.operations for t in ph["spec"]["tasks"])


# API
@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_api_assets(client):
    r = client.get("/v1/assets", params={"kind": "Runbook"})
    assert r.status_code == 200 and r.json()["count"] == 6
    assert client.get("/v1/assets/persona.devops").status_code == 200
    assert client.get("/v1/assets/nope").status_code == 404
    rev = client.get("/v1/operations/delivery.deploy/assets").json()
    assert "runbook.deploy_service" in rev["assets"]
