"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 6 entidades, upsert de
chave natural (mvp scope / product vision por `product`), soft-delete e ISOLAMENTO por
tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── User Stories ──────────────────────────────────────────────────────────────
async def test_user_story_crud(store_a):
    saved = await store_a.save_user_story(
        feature="login",
        role="usuário autenticado",
        goal="entrar com SSO",
        acceptance_criteria=["dado SSO válido, então acessa"],
        priority="high",
    )
    assert isinstance(saved["id"], int) and saved["id"] > 0
    assert saved["feature"] == "login"
    assert saved["acceptance_criteria"] == ["dado SSO válido, então acessa"]  # JSON round-trip

    got = await store_a.get_user_story(saved["id"])
    assert got is not None and got["role"] == "usuário autenticado"

    updated = await store_a.update_user_story(saved["id"], status="ready", priority="medium")
    assert updated is not None and updated["status"] == "ready" and updated["priority"] == "medium"

    listed = await store_a.list_user_stories(feature="login")
    assert len(listed) == 1
    assert await store_a.list_user_stories(role="usuário autenticado") != []

    assert await store_a.delete_user_story(saved["id"]) == 1
    assert await store_a.get_user_story(saved["id"]) is None
    assert await store_a.list_user_stories() == []


async def test_user_story_get_missing_returns_none(store_a):
    assert await store_a.get_user_story(999999) is None
    assert await store_a.update_user_story(999999, status="x") is None
    assert await store_a.delete_user_story(999999) == 0


# ── MVP Scopes (upsert por product) ───────────────────────────────────────────
async def test_mvp_scope_upsert_by_product(store_a):
    first = await store_a.set_mvp_scope("checkout", {"core_features": ["pagar"]}, goal="validar")
    assert first["product"] == "checkout"
    assert first["content"] == {"core_features": ["pagar"]}

    # mesmo product → upsert (não duplica), sobrescreve content/status
    second = await store_a.set_mvp_scope(
        "checkout", {"core_features": ["pagar", "reembolsar"]}, status="locked"
    )
    assert second["content"] == {"core_features": ["pagar", "reembolsar"]} and second["status"] == "locked"

    scopes = await store_a.list_mvp_scopes()
    assert len(scopes) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_mvp_scope("checkout")
    assert got is not None and got["goal"] == "validar"
    assert await store_a.get_mvp_scope("inexistente") is None

    assert await store_a.delete_mvp_scope("checkout") == 1
    assert await store_a.get_mvp_scope("checkout") is None


# ── Product Visions (upsert por product) ──────────────────────────────────────
async def test_product_vision_upsert_by_product(store_a):
    first = await store_a.set_product_vision(
        "acme", vision="ser o melhor", target_audience="PMEs", content={"goals": ["crescer"]}
    )
    assert first["product"] == "acme"
    assert first["content"] == {"goals": ["crescer"]}
    assert first["target_audience"] == "PMEs"

    second = await store_a.set_product_vision("acme", vision="dominar o mercado", status="approved")
    assert second["vision"] == "dominar o mercado" and second["status"] == "approved"

    visions = await store_a.list_product_visions()
    assert len(visions) == 1

    got = await store_a.get_product_vision("acme")
    assert got is not None and got["vision"] == "dominar o mercado"
    assert await store_a.get_product_vision("inexistente") is None

    assert await store_a.delete_product_vision("acme") == 1
    assert await store_a.get_product_vision("acme") is None


# ── User Personas (histórico) ─────────────────────────────────────────────────
async def test_user_persona_crud(store_a):
    saved = await store_a.save_user_persona(
        name="Ana Gestora",
        segment="B2B",
        demographics={"idade": "35-45"},
        goals=["reduzir custo"],
        pains=["planilhas manuais"],
        behaviors=["usa mobile"],
    )
    assert saved["id"] > 0
    assert saved["demographics"] == {"idade": "35-45"}
    assert saved["goals"] == ["reduzir custo"]
    assert saved["pains"] == ["planilhas manuais"]

    updated = await store_a.update_user_persona(saved["id"], segment="Enterprise", behaviors=["usa desktop"])
    assert updated["segment"] == "Enterprise" and updated["behaviors"] == ["usa desktop"]

    assert {p["id"] for p in await store_a.list_user_personas(segment="Enterprise")} == {saved["id"]}
    assert await store_a.list_user_personas(name="Ana Gestora") != []

    assert await store_a.delete_user_persona(saved["id"]) == 1
    assert await store_a.get_user_persona(saved["id"]) is None


# ── Backlog Items (score determinístico, ordenação por score) ─────────────────
async def test_backlog_item_crud_and_ordering(store_a):
    low = await store_a.save_backlog_item(name="baixa", framework="RICE", score=2.0)
    high = await store_a.save_backlog_item(name="alta", framework="RICE", score=42.0)
    assert low["id"] != high["id"]
    assert high["score"] == 42.0

    # list ordena por score desc → o item de score maior vem primeiro
    listed = await store_a.list_backlog_items()
    assert [i["id"] for i in listed] == [high["id"], low["id"]]
    assert {i["id"] for i in await store_a.list_backlog_items(framework="RICE")} == {low["id"], high["id"]}

    updated = await store_a.update_backlog_item(low["id"], status="done", score=5.0)
    assert updated["status"] == "done" and updated["score"] == 5.0

    got = await store_a.get_backlog_item(high["id"])
    assert got is not None and got["name"] == "alta"

    assert await store_a.delete_backlog_item(high["id"]) == 1
    assert await store_a.get_backlog_item(high["id"]) is None
    assert len(await store_a.list_backlog_items()) == 1


# ── Artifacts (histórico append-only) ─────────────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(kind="journey", target="onboarding", content={"stages": [1, 2]})
    a2 = await store_a.save_artifact(
        kind="gtm", target="acme", content={"channels": ["email"]}, meta={"v": 1}
    )
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"v": 1}
    assert a1["content"] == {"stages": [1, 2]}  # JSON round-trip

    assert {a["id"] for a in await store_a.list_artifacts(kind="journey")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="acme")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "journey"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_user_story(feature="only-in-a", role="x")
    await store_a.set_mvp_scope("prod-a", {"core_features": []})

    assert len(await store_a.list_user_stories()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_user_stories() == []
    assert await store_b.list_mvp_scopes() == []
    assert await store_b.get_mvp_scope("prod-a") is None
