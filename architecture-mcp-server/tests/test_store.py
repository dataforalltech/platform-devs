"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 4 entidades, upsert de
chave natural (modelo C4 por system_name), soft-delete e ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Architecture Blueprints ───────────────────────────────────────────────────
async def test_architecture_blueprint_crud(store_a):
    saved = await store_a.save_architecture_blueprint(
        name="ecom arch",
        domain="e-commerce",
        style="Microservices",
        constraints=["budget baixo"],
        quality_attributes=["scalability"],
        content={"rationale": {"style": "Microservices"}},
        status="proposed",
    )
    assert isinstance(saved["id"], int) and saved["id"] > 0
    assert saved["domain"] == "e-commerce"
    assert saved["constraints"] == ["budget baixo"]  # JSON round-trip
    assert saved["content"] == {"rationale": {"style": "Microservices"}}

    got = await store_a.get_architecture_blueprint(saved["id"])
    assert got is not None and got["style"] == "Microservices"

    updated = await store_a.update_architecture_blueprint(saved["id"], status="approved", style="Serverless")
    assert updated is not None and updated["status"] == "approved" and updated["style"] == "Serverless"

    listed = await store_a.list_architecture_blueprints(domain="e-commerce")
    assert len(listed) == 1
    assert await store_a.list_architecture_blueprints(status="approved") != []

    assert await store_a.delete_architecture_blueprint(saved["id"]) == 1
    assert await store_a.get_architecture_blueprint(saved["id"]) is None
    assert await store_a.list_architecture_blueprints() == []


async def test_architecture_blueprint_get_missing_returns_none(store_a):
    assert await store_a.get_architecture_blueprint(999999) is None
    assert await store_a.update_architecture_blueprint(999999, status="x") is None
    assert await store_a.delete_architecture_blueprint(999999) == 0


# ── C4 Diagrams (upsert por system_name) ──────────────────────────────────────
async def test_c4_diagram_upsert_by_system(store_a):
    first = await store_a.set_c4_diagram(
        "billing", model={"levels": {"container": {}}}, title="C4 — billing", status="draft"
    )
    assert first["system_name"] == "billing"
    assert first["model"] == {"levels": {"container": {}}}

    # mesmo system_name → upsert (não duplica), sobrescreve model/status
    second = await store_a.set_c4_diagram("billing", model={"levels": {"context": {}}}, status="final")
    assert second["model"] == {"levels": {"context": {}}} and second["status"] == "final"

    diagrams = await store_a.list_c4_diagrams()
    assert len(diagrams) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_c4_diagram("billing")
    assert got is not None and got["model"] == {"levels": {"context": {}}}
    assert await store_a.get_c4_diagram("inexistente") is None

    assert await store_a.delete_c4_diagram("billing") == 1
    assert await store_a.get_c4_diagram("billing") is None


# ── Solution Blueprints (histórico) ───────────────────────────────────────────
async def test_solution_blueprint_crud(store_a):
    saved = await store_a.save_solution_blueprint(
        solution_name="checkout",
        content={"layers": [{"name": "Data"}]},
        context="B2C SaaS",
        requirements="processar pagamento; emitir nota",
        status="draft",
    )
    assert saved["id"] > 0
    assert saved["content"] == {"layers": [{"name": "Data"}]}
    assert saved["requirements"] == "processar pagamento; emitir nota"

    updated = await store_a.update_solution_blueprint(saved["id"], status="approved", context="B2B")
    assert updated["status"] == "approved" and updated["context"] == "B2B"

    assert {b["id"] for b in await store_a.list_solution_blueprints(solution_name="checkout")} == {
        saved["id"]
    }
    assert await store_a.list_solution_blueprints(status="approved") != []

    assert await store_a.delete_solution_blueprint(saved["id"]) == 1
    assert await store_a.get_solution_blueprint(saved["id"]) is None


# ── Artifacts (histórico append-only) ─────────────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(
        kind="mermaid", target="billing", content="graph TD; A-->B", format="mermaid"
    )
    a2 = await store_a.save_artifact(kind="adr", target="platform", content="# ADR 1", meta={"num": 1})
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"num": 1}
    assert a2["content"] == "# ADR 1"  # texto livre, não JSON

    assert {a["id"] for a in await store_a.list_artifacts(kind="mermaid")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="platform")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "mermaid"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_architecture_blueprint(name="only-in-a", domain="only-in-a")
    await store_a.set_c4_diagram("sys-a", model={})

    assert len(await store_a.list_architecture_blueprints()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_architecture_blueprints() == []
    assert await store_b.list_c4_diagrams() == []
    assert await store_b.get_c4_diagram("sys-a") is None
