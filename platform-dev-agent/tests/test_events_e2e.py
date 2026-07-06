"""E2E Fase 4 (ADR-012) — o runtime emite eventos canônicos durante plan/execute.

Prova: envelope CloudEvents + taxonomia + correlação/causação, e que os eventos saem
dos pontos certos (CapabilityInvoked na borda de execução, PolicyDenied no PDP).
"""

from __future__ import annotations

import httpx
import pytest

from app.dev_agent.capability import CapabilityEnforcer
from app.dev_agent.catalog import (
    CapabilityRecord, InMemoryCatalogSource, PolicyEngine, RegistryCapabilityResolver,
)
from app.dev_agent.events import Event, EventType, InMemoryEventSink, new_ulid
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import Capability, ItemStatus
from app.dev_agent.plan.approval import ApprovalGate
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from app.dev_agent.pipeline import AutonomousPipeline
from app.dev_agent.runbook_selector import RunbookSelector
from tests._fake_gateway import FakeGateway, StaticTokenProvider

_ENFORCER = CapabilityEnforcer({
    "devops": {Capability.READ, Capability.WRITE},
    "qa-engineer": {Capability.READ, Capability.WRITE},
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


def _deploy_plan(resolver):
    return PlanBuilder(resolver).build_from_runbook(
        runbook_id="deploy_service", session_id="s-ev",
        inputs_by_task={"check_health": {"service": "api"}, "run_tests": {"suite": "unit"},
                        "deploy": {"service": "api", "version": "v1"}})


# --- envelope / model (unit) -------------------------------------------------
def test_envelope_topic_and_ulid():
    ev = Event(type=EventType.CAPABILITY_INVOKED, subject="capability/delivery.deploy",
               data={"x": 1}, tenant_id="acme", correlation_id="run_1")
    assert ev.topic == "platform.capability.v1"
    assert ev.partition_key == "acme"
    d = ev.to_dict()
    assert d["specversion"] == "1.0" and d["type"] == "com.dataforall.capability.invoked"
    assert len(ev.id) == 26 and len(new_ulid()) == 26          # ULID
    assert ev.headers()["ce_type"] == "com.dataforall.capability.invoked"


# --- executor: sequência completa + correlação/causação ----------------------
@pytest.mark.asyncio
async def test_executor_emits_full_lifecycle_with_causation():
    resolver = RegistryCapabilityResolver(_catalog())
    plan = _deploy_plan(resolver)
    fake, repo, sink = FakeGateway(), InMemoryPlanRepository(), InMemoryEventSink()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())
    deploy_id = plan.item_by_task("deploy").item_id
    decision = ApprovalGate().resolve(
        plan, response_value={"__approve_all__": True, "__confirm_high__": [deploy_id]})

    _ = [r async for r in ex.execute(plan, run_id="run_ev", decision=decision, emitter=_emitter(sink))]

    types = [e.type for e in sink.events]
    assert types[0] is EventType.EXECUTION_STARTED
    assert EventType.TASK_STARTED in types
    assert EventType.CAPABILITY_INVOKED in types
    assert EventType.TASK_FINISHED in types
    assert types[-2] is EventType.EXECUTION_COMPLETED
    assert types[-1] is EventType.RUNBOOK_COMPLETED
    # correlação = run_id em todos; cadeia causal íntegra (raiz sem causa).
    assert all(e.correlation_id == "run_ev" for e in sink.events)
    assert sink.events[0].causation_id is None
    for prev, cur in zip(sink.events, sink.events[1:]):
        assert cur.causation_id == prev.id
    # o deploy foi invocado com metadados do catálogo
    dep = [e for e in sink.of_type(EventType.CAPABILITY_INVOKED)
           if e.data["operation_id"] == "delivery.deploy"]
    assert dep and dep[0].data["blast_radius"] == "environment" and dep[0].data["outcome"] == "ok"


# --- executor: PolicyDenied sai do PDP ---------------------------------------
@pytest.mark.asyncio
async def test_policy_denied_emits_event():
    resolver = RegistryCapabilityResolver(_catalog())
    plan = _deploy_plan(resolver)
    items = [it.model_copy(update={"responsible": "qa-engineer"}) if it.task_id == "deploy" else it
             for it in plan.items]
    plan = plan.model_copy(update={"items": items})
    fake, repo, sink = FakeGateway(), InMemoryPlanRepository(), InMemoryEventSink()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())

    _ = [r async for r in ex.execute(plan, run_id="run_pd", decision=None, emitter=_emitter(sink))]

    denied = sink.of_type(EventType.POLICY_DENIED)
    assert len(denied) == 1
    assert denied[0].data["operation_id"] == "delivery.deploy"
    assert denied[0].data["actor"] == "qa-engineer"
    # deploy NÃO gerou CapabilityInvoked (nunca chegou à borda de execução)
    assert not any(e.data.get("operation_id") == "delivery.deploy"
                   for e in sink.of_type(EventType.CAPABILITY_INVOKED))


# --- pipeline: PlanCreated + PlanApproved (wiring ponta-a-ponta) --------------
@pytest.mark.asyncio
async def test_pipeline_emits_plan_and_execution_events():
    fake, repo, sink = FakeGateway(), InMemoryPlanRepository(), InMemoryEventSink()
    pipe = AutonomousPipeline(repo=repo, gateway=_client(fake), enforcer=_ENFORCER,
                              selector=RunbookSelector(), event_sink=sink)
    proposal = await pipe.plan(message="checar saúde", session_id="s1",
                               entity_type="service_health",
                               inputs_by_task={"check_health": {"service": "api"},
                                               "run_tests": {"suite": "unit"}})
    await pipe.execute(question_id=proposal.plan.question_id, response_value="__approve_all__",
                       run_id="run_pipe")

    types = {e.type for e in sink.events}
    assert EventType.PLAN_CREATED in types
    assert EventType.PLAN_APPROVED in types
    assert EventType.EXECUTION_STARTED in types
    assert EventType.EXECUTION_COMPLETED in types
    # PlanApproved e execução carregam o run_id como correlação.
    approved = [e for e in sink.events if e.type is EventType.PLAN_APPROVED][0]
    assert approved.correlation_id == "run_pipe"


def _emitter(sink):
    from app.dev_agent.events import EventEmitter
    return EventEmitter(sink, correlation_id="run_ev" , tenant_id="acme", session_id="s-ev")
