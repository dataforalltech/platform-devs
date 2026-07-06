"""E2E Fase 2 — o PolicyEngine enforça DURANTE a execução do plano.

Prova o gap fechado: o PlanExecutor chama decide() por item.
- qa_engineer tenta deploy  -> policy_denied (SKIPPED), tool NÃO chamada.
- devops deploy (HIGH)       -> policy PERMITE, mas exige N2 (SKIPPED sem confirmação);
                                com N2 confirmado -> executa (DONE).
O builder também usa o RegistryCapabilityResolver, então o deploy é classificado
write/high pelo CATÁLOGO (a heurística de verbo sozinha marcaria read/low após o
rename create_deployment->deploy) — isto é o catálogo virando source of truth.
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.capability import CapabilityEnforcer
from app.dev_agent.catalog import (
    CapabilityRecord, InMemoryCatalogSource, PolicyEngine, RegistryCapabilityResolver,
)
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import Capability, ItemStatus
from app.dev_agent.plan.approval import ApprovalGate
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from tests._fake_gateway import FakeGateway, StaticTokenProvider

_ENFORCER = CapabilityEnforcer({
    "devops": {Capability.READ, Capability.WRITE},
    "qa-engineer": {Capability.READ, Capability.WRITE},   # write concedido: quem barra é o PDP
})


def _client(fake: FakeGateway) -> GatewayToolClient:
    return GatewayToolClient(base_url="http://gateway.test/mcp",
                             token_provider=StaticTokenProvider(),
                             transport=httpx.ASGITransport(app=fake.app))


def _catalog() -> InMemoryCatalogSource:
    return InMemoryCatalogSource({
        "services-mcp.check_health": CapabilityRecord(
            "services-mcp.check_health", "infra.check_health", "infra", "read", "low",
            ("read",), "none", "none", "service"),
        "qa-mcp.run_unit_tests": CapabilityRecord(
            "qa-mcp.run_unit_tests", "testing.run_unit_tests", "testing", "read", "low",
            ("read",), "none", "none", "test"),
        "deploy-mcp.deploy": CapabilityRecord(
            "deploy-mcp.deploy", "delivery.deploy", "delivery", "write", "high",
            ("deploy",), "environment", "N2", "deployment"),
    })


def _deploy_plan(resolver: RegistryCapabilityResolver):
    return PlanBuilder(resolver).build_from_runbook(
        runbook_id="deploy_service", session_id="s-pol",
        inputs_by_task={"check_health": {"service": "api"}, "run_tests": {"suite": "unit"},
                        "deploy": {"service": "api", "version": "v1"}})


@pytest.mark.asyncio
async def test_qa_engineer_deploy_is_policy_denied():
    resolver = RegistryCapabilityResolver(_catalog())
    plan = _deploy_plan(resolver)
    # dono do deploy vira qa-engineer (read-only no PDP)
    items = [it.model_copy(update={"responsible": "qa-engineer"}) if it.task_id == "deploy" else it
             for it in plan.items]
    plan = plan.model_copy(update={"items": items})
    fake, repo = FakeGateway(), InMemoryPlanRepository()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())

    # decision=None => tudo aprovado (N2 fora) — quem barra o deploy é O PDP.
    results = {r.task_id: r async for r in ex.execute(plan, run_id="r", decision=None)}

    assert results["deploy"].status is ItemStatus.SKIPPED
    assert "policy_denied" in results["deploy"].error
    assert not any(t == "deploy-mcp.deploy" for t, _ in fake.idempotency_keys)  # não executou
    assert results["check_health"].status is ItemStatus.DONE                    # reads passaram


@pytest.mark.asyncio
async def test_devops_deploy_requires_n2_even_when_policy_allows():
    resolver = RegistryCapabilityResolver(_catalog())
    plan = _deploy_plan(resolver)                     # deploy é devops (padrão do runbook)
    fake, repo = FakeGateway(), InMemoryPlanRepository()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())

    # N1 aprova tudo; N2 NÃO confirmado -> deploy barrado pelo N2 (policy permitiria).
    decision = ApprovalGate().resolve(plan, response_value="__approve_all__")
    results = {r.task_id: r async for r in ex.execute(plan, run_id="r", decision=decision)}

    assert results["deploy"].status is ItemStatus.SKIPPED
    assert "N2" in results["deploy"].error
    assert "policy_denied" not in results["deploy"].error   # policy PERMITIU devops


@pytest.mark.asyncio
async def test_devops_deploy_executes_with_policy_allow_and_n2():
    resolver = RegistryCapabilityResolver(_catalog())
    plan = _deploy_plan(resolver)
    fake, repo = FakeGateway(), InMemoryPlanRepository()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())
    deploy_id = plan.item_by_task("deploy").item_id

    decision = ApprovalGate().resolve(
        plan, response_value={"__approve_all__": True, "__confirm_high__": [deploy_id]})
    results = {r.task_id: r async for r in ex.execute(plan, run_id="r", decision=decision)}

    assert results["deploy"].status is ItemStatus.DONE      # policy allow + N2 confirmado
    assert any(t == "deploy-mcp.deploy" for t, _ in fake.idempotency_keys)
