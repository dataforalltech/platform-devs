"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 5 entidades, upsert de
chave natural (visão por product), soft-delete e ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Feature Specs ─────────────────────────────────────────────────────────────
async def test_feature_spec_crud(store_a):
    saved = await store_a.save_feature_spec(
        feature="login",
        content={"user_stories": ["como user..."]},
        objective="permitir login",
        priority="high",
    )
    assert isinstance(saved["id"], int) and saved["id"] > 0
    assert saved["feature"] == "login"
    assert saved["content"] == {"user_stories": ["como user..."]}  # JSON round-trip

    got = await store_a.get_feature_spec(saved["id"])
    assert got is not None and got["objective"] == "permitir login"

    updated = await store_a.update_feature_spec(saved["id"], status="approved", priority="medium")
    assert updated is not None and updated["status"] == "approved" and updated["priority"] == "medium"

    listed = await store_a.list_feature_specs(feature="login")
    assert len(listed) == 1
    assert await store_a.list_feature_specs(status="approved") != []

    assert await store_a.delete_feature_spec(saved["id"]) == 1
    assert await store_a.get_feature_spec(saved["id"]) is None
    assert await store_a.list_feature_specs() == []


async def test_feature_spec_get_missing_returns_none(store_a):
    assert await store_a.get_feature_spec(999999) is None
    assert await store_a.update_feature_spec(999999, status="x") is None
    assert await store_a.delete_feature_spec(999999) == 0


# ── GTM Briefs ────────────────────────────────────────────────────────────────
async def test_gtm_brief_crud(store_a):
    saved = await store_a.save_gtm_brief(
        product="checkout",
        content={"channels": ["site", "sales"]},
        launch_timing="Q2 2026",
    )
    assert saved["id"] > 0
    assert saved["content"] == {"channels": ["site", "sales"]}
    assert saved["launch_timing"] == "Q2 2026"

    updated = await store_a.update_gtm_brief(saved["id"], status="ready", launch_timing="Q3 2026")
    assert updated["status"] == "ready" and updated["launch_timing"] == "Q3 2026"

    assert {b["id"] for b in await store_a.list_gtm_briefs(product="checkout")} == {saved["id"]}
    assert await store_a.list_gtm_briefs(status="ready") != []

    assert await store_a.delete_gtm_brief(saved["id"]) == 1
    assert await store_a.get_gtm_brief(saved["id"]) is None


# ── Release Plans ─────────────────────────────────────────────────────────────
async def test_release_plan_crud(store_a):
    saved = await store_a.save_release_plan(
        product="mobile",
        content={"phases": ["alpha", "beta", "ga"]},
        status="planned",
    )
    assert saved["id"] > 0
    assert saved["content"] == {"phases": ["alpha", "beta", "ga"]}

    updated = await store_a.update_release_plan(saved["id"], status="in_progress")
    assert updated["status"] == "in_progress"

    assert {p["id"] for p in await store_a.list_release_plans(product="mobile")} == {saved["id"]}
    assert await store_a.list_release_plans(status="in_progress") != []

    assert await store_a.delete_release_plan(saved["id"]) == 1
    assert await store_a.get_release_plan(saved["id"]) is None


# ── Product Visions (upsert por product) ──────────────────────────────────────
async def test_product_vision_upsert_by_product(store_a):
    first = await store_a.set_product_vision("acme", vision="ser o melhor", goals=["market"], status="active")
    assert first["product"] == "acme"
    assert first["goals"] == ["market"]

    # mesmo product → upsert (não duplica), sobrescreve vision/goals/status
    second = await store_a.set_product_vision("acme", vision="ser o líder", goals=["market", "nps"])
    assert second["vision"] == "ser o líder" and second["goals"] == ["market", "nps"]

    visions = await store_a.list_product_visions()
    assert len(visions) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_product_vision("acme")
    assert got is not None and got["goals"] == ["market", "nps"]
    assert await store_a.get_product_vision("inexistente") is None

    assert await store_a.delete_product_vision("acme") == 1
    assert await store_a.get_product_vision("acme") is None


# ── Artifacts (histórico append-only) ─────────────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(kind="roadmap", target="acme", content="# Roadmap 2026", fmt="markdown")
    a2 = await store_a.save_artifact(kind="prd", target="feature-x", content="PRD body", meta={"v": 2})
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"v": 2}
    assert a2["content"] == "PRD body"  # texto livre, não JSON

    assert {a["id"] for a in await store_a.list_artifacts(kind="roadmap")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="feature-x")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "roadmap"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_feature_spec(feature="only-in-a", content={})
    await store_a.set_product_vision("prod-a", vision="x")

    assert len(await store_a.list_feature_specs()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_feature_specs() == []
    assert await store_b.list_product_visions() == []
    assert await store_b.get_product_vision("prod-a") is None
