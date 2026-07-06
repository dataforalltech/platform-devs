"""Fase 1.1 — admin/auth federados + o fallback continua íntegro para tools não-catalogadas.

Depois da federação (platform-catalog/external), platform_health RESOLVE 100%. Este teste
prova: (a) admin/auth agora têm Operation; (b) platform_health executa resolvido pelo
catálogo; (c) o fallback (migração aditiva D9.10) segue válido para qualquer tool que o
catálogo NÃO conhece.
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.capability import CapabilityEnforcer
from app.dev_agent.catalog import DirCatalogSource, PolicyEngine, RegistryCapabilityResolver
from app.dev_agent.catalog.ingest import build_all
from app.dev_agent.events import EventEmitter, EventType, InMemoryEventSink
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import Capability, ItemStatus
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from tests._fake_gateway import FakeGateway, StaticTokenProvider

_ENFORCER = CapabilityEnforcer({"devops": {Capability.READ, Capability.WRITE},
                                "qa-engineer": {Capability.READ, Capability.WRITE}})
_ADMIN_AUTH = {"admin.admin_health_check", "auth.auth_health_check", "auth.auth_list_tenants"}


def _client(fake):
    return GatewayToolClient(base_url="http://gateway.test/mcp",
                             token_provider=StaticTokenProvider(),
                             transport=httpx.ASGITransport(app=fake.app))


def test_admin_auth_are_federated_now():
    """Fase 1.1: as tools admin/auth passaram a ter Operation (external) no catálogo."""
    src = DirCatalogSource()
    for t in _ADMIN_AUTH:
        rec = src.record(t)
        assert rec is not None, f"{t} deveria estar federada"
        assert rec.operation_id == t


@pytest.mark.asyncio
async def test_platform_health_executes_resolved_by_catalog():
    resolver = RegistryCapabilityResolver(DirCatalogSource())
    plan = PlanBuilder(resolver).build_from_runbook(runbook_id="platform_health", session_id="s")
    fake, repo, sink = FakeGateway(), InMemoryPlanRepository(), InMemoryEventSink()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())
    emitter = EventEmitter(sink, correlation_id="run_ph")

    results = {r.task_id: r async for r in ex.execute(plan, run_id="run_ph", decision=None,
                                                       emitter=emitter)}
    assert all(r.status is ItemStatus.DONE for r in results.values())
    assert not sink.of_type(EventType.POLICY_DENIED)          # admin/auth são read → permitido
    cap = {e.data["tool_id"]: e for e in sink.of_type(EventType.CAPABILITY_INVOKED)}
    # operation_id vem do CATÁLOGO agora (resolvido), não do fallback
    assert cap["admin.admin_health_check"].data["operation_id"] == "admin.admin_health_check"


def test_fallback_still_works_for_uncatalogued_tool():
    """Uma tool que o catálogo NÃO conhece continua caindo na heurística (D9.10)."""
    r = RegistryCapabilityResolver(DirCatalogSource())
    assert r.record("nonexistent-mcp.frobnicate") is None
    assert r.resolve("nonexistent-mcp.create_thing") is Capability.WRITE   # heurística: create_ → write
    assert r.resolve("nonexistent-mcp.get_thing") is Capability.READ


def test_platform_health_asset_fully_resolved():
    ph = {a["metadata"]["uid"]: a for a in build_all()}["runbook.platform_health"]
    assert ph["spec"]["unresolved_tools"] == 0
    assert all(t["resolved"] and t["operation_id"] in _ADMIN_AUTH for t in ph["spec"]["tasks"])
