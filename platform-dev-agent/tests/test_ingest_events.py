"""Fase 5 — ingestão de assets emite AssetPublished/AssetPromoted (ADR-014/012)."""

from __future__ import annotations

from app.dev_agent.catalog.ingest import build_all, ingest_all, promote
from app.dev_agent.events import EventType, InMemoryEventSink


def test_build_all_produces_asset_kinds():
    by_kind: dict[str, int] = {}
    for a in build_all():
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    assert by_kind["Runbook"] == 6
    assert by_kind["Persona"] == 8 and by_kind["Prompt"] == 8 and by_kind["Policy"] == 8
    assert by_kind.get("ADR", 0) >= 9


def test_wave1_runbooks_resolve_operation_first():
    """Fase 6 — os 3 runbooks Operation-first resolvem 100% (Operation, sem tool-only)."""
    assets = {a["metadata"]["uid"]: a for a in build_all()}
    for rid in ("hotfix", "architecture_review", "incident"):
        rb = assets[f"runbook.{rid}"]
        assert rb["spec"]["unresolved_tools"] == 0
        for t in rb["spec"]["tasks"]:
            assert t["resolved"] is True
            assert t["operation_id"]                       # Operation-first: op_id set
            assert t["tool"]                               # concrete tool resolved
    # hotfix's deploy step maps to the delivery.deploy Operation.
    hotfix = assets["runbook.hotfix"]
    deploy = next(t for t in hotfix["spec"]["tasks"] if t["task_id"] == "deploy")
    assert deploy["operation_id"] == "delivery.deploy"


def test_runbook_resolves_tool_to_operation():
    assets = {a["metadata"]["uid"]: a for a in build_all()}
    dep = assets["runbook.deploy_service"]
    assert all(t["resolved"] for t in dep["spec"]["tasks"])                   # tudo resolvido
    assert any(t["operation_id"] == "delivery.deploy" for t in dep["spec"]["tasks"])
    # Fase 1.1: admin/auth federados → platform_health resolve 100% (fallback p/ tool
    # sintética coberto em test_fallback_platform_health).
    ph = assets["runbook.platform_health"]
    assert ph["spec"]["unresolved_tools"] == 0
    assert all(t["resolved"] for t in ph["spec"]["tasks"])


def test_ingest_emits_asset_published_per_asset():
    sink = InMemoryEventSink()
    summary = ingest_all(sink=sink, write=False)                             # não escreve YAML no teste
    published = sink.of_type(EventType.ASSET_PUBLISHED)
    assert len(published) == summary["total"]
    # todos no tópico de asset, com kind/version no data
    assert all(e.topic == "platform.asset.v1" for e in published)
    kinds = {e.data["kind"] for e in published}
    assert {"Runbook", "Persona", "Prompt", "Policy", "ADR"} <= kinds


def test_promote_emits_asset_promoted():
    sink = InMemoryEventSink()
    promote(asset_ref="runbook.deploy_service", kind="Runbook", version="1.0.0",
            approver="user:caio", sink=sink, from_="draft", to="active")
    ev = sink.of_type(EventType.ASSET_PROMOTED)
    assert len(ev) == 1
    assert ev[0].data["to"] == "active" and ev[0].data["approver"] == "user:caio"
    assert ev[0].topic == "platform.asset.v1"
