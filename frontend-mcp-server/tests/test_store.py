"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 5 entidades, upsert de
chave natural (página por route), soft-delete e ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Components ────────────────────────────────────────────────────────────────
async def test_component_crud(store_a):
    saved = await store_a.save_component(
        name="Button",
        variant="functional",
        framework="react",
        styling="tailwind",
        props={"label": "string"},
        code="export const Button = () => <button/>",
    )
    assert isinstance(saved["id"], int) and saved["id"] > 0
    assert saved["name"] == "Button"
    assert saved["props"] == {"label": "string"}  # JSON round-trip
    assert saved["code"] == "export const Button = () => <button/>"  # texto livre

    got = await store_a.get_component(saved["id"])
    assert got is not None and got["framework"] == "react"

    updated = await store_a.update_component(saved["id"], status="published", variant="class")
    assert updated is not None and updated["status"] == "published" and updated["variant"] == "class"

    listed = await store_a.list_components(name="Button")
    assert len(listed) == 1
    assert await store_a.list_components(framework="react") != []

    assert await store_a.delete_component(saved["id"]) == 1
    assert await store_a.get_component(saved["id"]) is None
    assert await store_a.list_components() == []


async def test_component_get_missing_returns_none(store_a):
    assert await store_a.get_component(999999) is None
    assert await store_a.update_component(999999, status="x") is None
    assert await store_a.delete_component(999999) == 0


# ── Pages (upsert por route) ──────────────────────────────────────────────────
async def test_page_upsert_by_route(store_a):
    first = await store_a.set_page(
        "/dashboard", title="Dashboard", framework="nextjs", page_type="app-route", meta={"layout": "root"}
    )
    assert first["route"] == "/dashboard"
    assert first["meta"] == {"layout": "root"}  # JSON round-trip

    # mesma route → upsert (não duplica), sobrescreve title/meta/status
    second = await store_a.set_page("/dashboard", title="Home", meta={"layout": "alt"}, status="published")
    assert second["title"] == "Home" and second["status"] == "published"
    assert second["meta"] == {"layout": "alt"}

    pages = await store_a.list_pages()
    assert len(pages) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_page("/dashboard")
    assert got is not None and got["title"] == "Home"
    assert await store_a.get_page("/inexistente") is None

    assert await store_a.delete_page("/dashboard") == 1
    assert await store_a.get_page("/dashboard") is None


# ── Forms ─────────────────────────────────────────────────────────────────────
async def test_form_crud(store_a):
    saved = await store_a.save_form(
        name="LoginForm",
        library="react-hook-form",
        validation="zod",
        fields=[{"name": "email", "type": "string"}],
        code="const LoginForm = () => {}",
    )
    assert saved["id"] > 0
    assert saved["fields"] == [{"name": "email", "type": "string"}]

    updated = await store_a.update_form(saved["id"], validation="yup", status="ready")
    assert updated["validation"] == "yup" and updated["status"] == "ready"

    assert {f["id"] for f in await store_a.list_forms(name="LoginForm")} == {saved["id"]}
    assert await store_a.list_forms(status="ready") != []

    assert await store_a.delete_form(saved["id"]) == 1
    assert await store_a.get_form(saved["id"]) is None


# ── Stories ───────────────────────────────────────────────────────────────────
async def test_story_crud(store_a):
    saved = await store_a.save_story(
        component="Button",
        title="Button stories",
        framework="storybook",
        stories=["Default", "Loading", "Error"],
        code="export default { component: Button }",
    )
    assert saved["id"] > 0
    assert saved["stories"] == ["Default", "Loading", "Error"]

    updated = await store_a.update_story(saved["id"], status="approved")
    assert updated["status"] == "approved"

    assert {s["id"] for s in await store_a.list_stories(component="Button")} == {saved["id"]}
    assert await store_a.list_stories(status="approved") != []

    assert await store_a.delete_story(saved["id"]) == 1
    assert await store_a.get_story(saved["id"]) is None


# ── Artifacts (histórico append-only) ─────────────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(
        kind="hook", target="useAuth", content="export function useAuth() {}", framework="react"
    )
    a2 = await store_a.save_artifact(
        kind="layout", target="RootLayout", content="<html/>", meta={"nested": True}
    )
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"nested": True}
    assert a2["content"] == "<html/>"  # texto livre, não JSON

    assert {a["id"] for a in await store_a.list_artifacts(kind="hook")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="RootLayout")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "hook"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_component(name="OnlyInA")
    await store_a.set_page("/only-in-a", title="A")

    assert len(await store_a.list_components()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_components() == []
    assert await store_b.list_pages() == []
    assert await store_b.get_page("/only-in-a") is None
