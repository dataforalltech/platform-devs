"""Store canônico contra MySQL real (§16 / FID-02): CRUD, upsert de chave natural,
normalização items/approvals, soft-delete no re-audit, criticidade persistida e
ISOLAMENTO por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Auditorias ────────────────────────────────────────────────────────────────
async def test_create_and_get_audit(store_a):
    audit_id = await store_a.create_audit(
        service="svc",
        repo="o/svc",
        env="dev",
        criticality="medium",
        score=0.75,
        passed=True,
        status="approved",
        checklist={"foo": "bar"},
    )
    assert audit_id == "audit_svc_dev"  # chave determinística preservada (string)

    audit = await store_a.get_audit(audit_id)
    assert audit is not None
    assert audit["id"] == audit_id  # id público = audit_key (não o surrogate INT)
    assert audit["service"] == "svc"
    assert audit["score"] == 0.75
    assert audit["passed"] is True  # 0/1 -> bool
    assert audit["checklist"] == {"foo": "bar"}  # JSON round-trip


async def test_get_audit_none_when_absent(store_a):
    assert await store_a.get_audit("audit_missing_dev") is None


async def test_create_audit_is_upsert_and_resets_children(store_a):
    aid = await store_a.create_audit("svc", "o/svc", "dev", "medium", 0.5, False, "pending_approval", {})
    await store_a.add_audit_item(aid, "structure", "has_src_dir", True, True, "ok")
    await store_a.add_approval(aid, "alice", "approved", role="lead")
    assert len(await store_a.get_audit_items(aid)) == 1
    assert len(await store_a.get_approvals(aid)) == 1

    # Re-auditoria: mesma chave -> sobrescreve a linha e ZERA os filhos.
    aid2 = await store_a.create_audit("svc", "o/svc", "dev", "high", 0.9, True, "approved", {})
    assert aid2 == aid  # mesma chave natural
    assert await store_a.get_audit_items(aid) == []
    assert await store_a.get_approvals(aid) == []
    # não duplicou a auditoria (upsert, não insert)
    assert len(await store_a.list_audits()) == 1
    assert (await store_a.get_audit(aid))["criticality"] == "high"


async def test_get_latest_audit(store_a):
    await store_a.create_audit("svc", "r", "prod", "high", 0.9, True, "approved", {})
    latest = await store_a.get_latest_audit("svc", "prod")
    assert latest is not None
    assert latest["service"] == "svc"
    assert await store_a.get_latest_audit("svc", "dev") is None


async def test_list_audits_filters(store_a):
    await store_a.create_audit("a", "r", "dev", "medium", 0.5, False, "pending_approval", {})
    await store_a.create_audit("b", "r", "prod", "high", 0.9, True, "approved", {})

    assert len(await store_a.list_audits()) == 2
    assert {a["service"] for a in await store_a.list_audits(env="dev")} == {"a"}
    assert {a["service"] for a in await store_a.list_audits(status="approved")} == {"b"}
    assert {a["service"] for a in await store_a.list_audits(service="a")} == {"a"}
    assert len(await store_a.list_audits(limit=1)) == 1


async def test_update_audit_status(store_a):
    aid = await store_a.create_audit("svc", "r", "dev", "medium", 0.0, False, "pending_approval", {})
    await store_a.update_audit_status(aid, "approved", 0.95, True)
    audit = await store_a.get_audit(aid)
    assert audit["status"] == "approved"
    assert audit["score"] == 0.95
    assert audit["passed"] is True


# ── Items (tabela normalizada) ────────────────────────────────────────────────
async def test_add_and_get_audit_items(store_a):
    aid = await store_a.create_audit("svc", "r", "dev", "medium", 0.0, False, "pending_approval", {})
    assert await store_a.get_audit_items(aid) == []
    await store_a.add_audit_item(aid, "structure", "has_src_dir", True, True, "ok")
    await store_a.add_audit_item(aid, "docs", "has_readme", False, False, None)
    items = await store_a.get_audit_items(aid)
    assert len(items) == 2
    by_name = {i["name"]: i for i in items}
    assert by_name["has_src_dir"]["required"] is True
    assert by_name["has_src_dir"]["passed"] is True
    assert by_name["has_readme"]["required"] is False


# ── Aprovações (tabela normalizada) ───────────────────────────────────────────
async def test_add_and_get_approvals(store_a):
    aid = await store_a.create_audit("svc", "r", "dev", "medium", 0.8, True, "pending_approval", {})
    assert await store_a.get_approvals("audit_missing_dev") == []
    await store_a.add_approval(aid, "alice", "approved", role="lead", notes="lgtm")
    approvals = await store_a.get_approvals(aid)
    assert len(approvals) == 1
    assert approvals[0]["approved_by"] == "alice"
    assert approvals[0]["role"] == "lead"
    assert approvals[0]["decision"] == "approved"


# ── Criticidade por serviço (antes stub NO-OP; agora persiste de verdade) ─────
async def test_service_criticality_persists(store_a):
    # default quando não definida
    assert await store_a.get_service_criticality("my-service") == "medium"
    await store_a.set_service_criticality("my-service", "high", "admin")
    assert await store_a.get_service_criticality("my-service") == "high"
    # upsert na chave natural (service): re-set atualiza, não duplica
    await store_a.set_service_criticality("my-service", "critical", "ana")
    assert await store_a.get_service_criticality("my-service") == "critical"
    # serviço desconhecido continua default
    assert await store_a.get_service_criticality("unknown") == "medium"


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.create_audit("only-in-a", "o/a", "dev", "medium", 0.5, False, "pending_approval", {})
    await store_a.set_service_criticality("only-in-a", "high", "admin")
    assert len(await store_a.list_audits()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_audits() == []
    assert await store_b.get_audit("audit_only-in-a_dev") is None
    assert await store_b.get_service_criticality("only-in-a") == "medium"
