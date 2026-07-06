"""Fecha o loop da ADR-012: Runtime → (Kafka) → Consumer → Timeline/Audit.

Prova: dedup por id (at-least-once), reconstrução por correlation_id=run_id,
round-trip do envelope (Kafka fake via to_dict/from_dict) e provisionamento dos tópicos.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.dev_agent.capability import CapabilityEnforcer
from app.dev_agent.catalog import (
    CapabilityRecord, InMemoryCatalogSource, PolicyEngine, RegistryCapabilityResolver,
)
from app.dev_agent.events import (
    TOPICS, AuditProjection, Event, EventConsumer, EventType, InMemoryEventSink,
    TimelineProjection,
)
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.models.plan import Capability
from app.dev_agent.plan.approval import ApprovalGate
from app.dev_agent.plan.builder import PlanBuilder
from app.dev_agent.plan.executor import PlanExecutor
from app.dev_agent.plan.repository import InMemoryPlanRepository
from tests._fake_gateway import FakeGateway, StaticTokenProvider

_ENFORCER = CapabilityEnforcer({"devops": {Capability.READ, Capability.WRITE}})


def _client(fake):
    return GatewayToolClient(base_url="http://gateway.test/mcp",
                             token_provider=StaticTokenProvider(),
                             transport=httpx.ASGITransport(app=fake.app))


def _catalog():
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


async def _run_and_collect() -> InMemoryEventSink:
    resolver = RegistryCapabilityResolver(_catalog())
    plan = PlanBuilder(resolver).build_from_runbook(
        runbook_id="deploy_service", session_id="s",
        inputs_by_task={"check_health": {"service": "api"}, "run_tests": {"suite": "unit"},
                        "deploy": {"service": "api", "version": "v1"}})
    fake, repo, sink = FakeGateway(), InMemoryPlanRepository(), InMemoryEventSink()
    await repo.create(plan)
    ex = PlanExecutor(repo, _client(fake), _ENFORCER, resolver=resolver, policy=PolicyEngine())
    from app.dev_agent.events import EventEmitter
    emitter = EventEmitter(sink, correlation_id="run_x", tenant_id="acme", session_id="s")
    deploy_id = plan.item_by_task("deploy").item_id
    decision = ApprovalGate().resolve(
        plan, response_value={"__approve_all__": True, "__confirm_high__": [deploy_id]})
    _ = [r async for r in ex.execute(plan, run_id="run_x", decision=decision, emitter=emitter)]
    return sink


# --- provisionamento dos tópicos --------------------------------------------
def test_topics_v1_cover_all_aggregates_with_retention():
    names = {t.name for t in TOPICS}
    assert names == {"platform.plan.v1", "platform.approval.v1", "platform.execution.v1",
                     "platform.capability.v1", "platform.policy.v1", "platform.delivery.v1",
                     "platform.asset.v1"}
    by = {t.name: t for t in TOPICS}
    assert by["platform.policy.v1"].retention_ms == 365 * 86_400_000        # 1 ano
    assert by["platform.execution.v1"].retention_ms == 30 * 86_400_000      # 30 d
    assert "compact" in by["platform.approval.v1"].cleanup_policy           # trilha


# --- consumer: timeline + audit ---------------------------------------------
@pytest.mark.asyncio
async def test_timeline_reconstructs_run_by_correlation():
    sink = await _run_and_collect()
    tl, audit = TimelineProjection(), AuditProjection()
    consumer = EventConsumer([tl, audit])
    for e in sink.events:
        consumer.consume(e)

    types = tl.types("run_x")
    assert types[0] is EventType.EXECUTION_STARTED
    assert types[-1] is EventType.RUNBOOK_COMPLETED
    assert EventType.CAPABILITY_INVOKED in types
    # ordem por (time,id) preservada
    tsorted = tl.timeline("run_x")
    assert [e.id for e in tsorted] == [e.id for e in sorted(tsorted, key=lambda x: (x.time, x.id))]
    # auditoria capturou a invocação de capability (write/deploy)
    assert any(r["detail"].get("operation_id") == "delivery.deploy" for r in audit.trail)


@pytest.mark.asyncio
async def test_dedup_by_event_id_at_least_once():
    sink = await _run_and_collect()
    tl = TimelineProjection()
    consumer = EventConsumer([tl])
    # entrega dupla (at-least-once): cada evento consumido duas vezes
    applied = sum(consumer.consume(e) for e in sink.events)          # 1ª vez: todos aplicam
    redelivered = sum(consumer.consume(e) for e in sink.events)      # 2ª vez: todos dedupados
    assert applied == len(sink.events)
    assert redelivered == 0
    assert len(tl.timeline("run_x")) == applied                      # sem duplicata na timeline


@pytest.mark.asyncio
async def test_kafka_wire_roundtrip_via_envelope():
    """'Kafka fake': serializa o envelope (value) e reconstrói — prova o formato de fio."""
    sink = await _run_and_collect()
    tl = TimelineProjection()
    consumer = EventConsumer([tl])
    for e in sink.events:
        wire = json.loads(json.dumps(e.to_dict()))                  # value serializado/desserializado
        assert consumer.consume_dict(wire)
    # a timeline reconstruída a partir do fio é idêntica em tipos/ordem
    assert tl.types("run_x")[0] is EventType.EXECUTION_STARTED
    assert tl.types("run_x")[-1] is EventType.RUNBOOK_COMPLETED
    # round-trip preserva o envelope
    e0 = sink.events[0]
    assert Event.from_dict(e0.to_dict()).id == e0.id
