"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 4 entidades, upsert de
chave natural (controle por (system_name, control_key)), soft-delete e ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Threat Models ─────────────────────────────────────────────────────────────
async def test_threat_model_crud(store_a):
    saved = await store_a.save_threat_model(
        system_name="checkout",
        methodology="STRIDE",
        title="TM checkout",
        components=["api", "db"],
        threats=[{"id": "T01", "category": "Spoofing"}],
        summary="avaliação inicial",
    )
    assert isinstance(saved["id"], int) and saved["id"] > 0
    assert saved["system_name"] == "checkout"
    assert saved["components"] == ["api", "db"]  # JSON round-trip
    assert saved["threats"] == [{"id": "T01", "category": "Spoofing"}]

    got = await store_a.get_threat_model(saved["id"])
    assert got is not None and got["title"] == "TM checkout"

    updated = await store_a.update_threat_model(saved["id"], status="approved", methodology="PASTA")
    assert updated is not None and updated["status"] == "approved" and updated["methodology"] == "PASTA"

    listed = await store_a.list_threat_models(system_name="checkout")
    assert len(listed) == 1
    assert await store_a.list_threat_models(status="approved") != []

    assert await store_a.delete_threat_model(saved["id"]) == 1
    assert await store_a.get_threat_model(saved["id"]) is None
    assert await store_a.list_threat_models() == []


async def test_threat_model_get_missing_returns_none(store_a):
    assert await store_a.get_threat_model(999999) is None
    assert await store_a.update_threat_model(999999, status="x") is None
    assert await store_a.delete_threat_model(999999) == 0


# ── Security Controls (upsert por (system_name, control_key)) ──────────────────────
async def test_security_control_upsert_by_natural_key(store_a):
    first = await store_a.set_security_control(
        "checkout", "authentication", name="MFA", control_type="technical", details={"nist": "PR.AC"}
    )
    assert first["system_name"] == "checkout" and first["control_key"] == "authentication"
    assert first["details"] == {"nist": "PR.AC"}

    # mesma (system_name, control_key) → upsert (não duplica), sobrescreve name/status
    second = await store_a.set_security_control(
        "checkout", "authentication", name="MFA+WebAuthn", status="enforced"
    )
    assert second["name"] == "MFA+WebAuthn" and second["status"] == "enforced"

    controls = await store_a.list_security_controls()
    assert len(controls) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_security_control("checkout", "authentication")
    assert got is not None and got["name"] == "MFA+WebAuthn"
    assert await store_a.get_security_control("checkout", "inexistente") is None

    # outra chave no mesmo sistema → nova linha
    await store_a.set_security_control("checkout", "encryption", name="TLS1.3")
    assert len(await store_a.list_security_controls(system_name="checkout")) == 2

    assert await store_a.delete_security_control("checkout", "authentication") == 1
    assert await store_a.get_security_control("checkout", "authentication") is None


# ── CVSS Assessments (histórico append-only) ──────────────────────────────────
async def test_cvss_assessment_crud(store_a):
    a1 = await store_a.save_cvss_assessment(
        vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        label="CVE-2024-1",
        base_score=9.8,
        severity="Critical",
        metrics={"AV": "N"},
    )
    a2 = await store_a.save_cvss_assessment(vector="CVSS:3.1/...", base_score=5.0, severity="Medium")
    assert a1["id"] != a2["id"]
    assert a1["base_score"] == 9.8 and a1["severity"] == "Critical"
    assert a1["metrics"] == {"AV": "N"}  # JSON round-trip

    assert {a["id"] for a in await store_a.list_cvss_assessments(severity="Critical")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_cvss_assessments(label="CVE-2024-1")} == {a1["id"]}
    assert len(await store_a.list_cvss_assessments()) == 2

    got = await store_a.get_cvss_assessment(a1["id"])
    assert got is not None and got["label"] == "CVE-2024-1"

    assert await store_a.delete_cvss_assessment(a1["id"]) == 1
    assert await store_a.get_cvss_assessment(a1["id"]) is None
    assert len(await store_a.list_cvss_assessments()) == 1


# ── Security Artifacts (histórico append-only) ────────────────────────────────
async def test_security_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(kind="incident_plan", target="checkout", content="runbook NIST 800-61")
    a2 = await store_a.save_artifact(kind="secrets_scan", target="/repo", content="0 findings", meta={"n": 0})
    assert a1["id"] != a2["id"]
    assert a2["meta"] == {"n": 0}
    assert a2["content"] == "0 findings"  # texto livre, não JSON

    assert {a["id"] for a in await store_a.list_artifacts(kind="incident_plan")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="/repo")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "incident_plan"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_threat_model(system_name="only-in-a")
    await store_a.set_security_control("svc-a", "authentication", name="MFA")

    assert len(await store_a.list_threat_models()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_threat_models() == []
    assert await store_b.list_security_controls() == []
    assert await store_b.get_security_control("svc-a", "authentication") is None
