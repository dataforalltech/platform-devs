"""Consumidores canônicos: Timeline + Audit (ADR-012 D12.10).

Fecha o loop da ADR-012: Runtime → Kafka → **Consumer → visão auditável/timeline**.
- Dedup obrigatório por `event.id` (ULID) — at-least-once (D12.7).
- Reconstrução de uma execução por `correlation_id = run_id` (D12.4).
As projeções são puras (aplicam eventos em memória); o loop Kafka é opcional (lazy).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.dev_agent.events.model import Event, EventType


@runtime_checkable
class Projection(Protocol):
    def apply(self, event: Event) -> None: ...


class TimelineProjection:
    """Linha do tempo por run (UX): eventos de um `correlation_id`, ordenados no tempo."""

    def __init__(self) -> None:
        self.runs: dict[str, list[Event]] = {}

    def apply(self, event: Event) -> None:
        if event.correlation_id:
            self.runs.setdefault(event.correlation_id, []).append(event)

    def timeline(self, run_id: str) -> list[Event]:
        # ULID é ordenável no tempo -> (time, id) reconstrói a ordem causal.
        return sorted(self.runs.get(run_id, []), key=lambda e: (e.time, e.id))

    def types(self, run_id: str) -> list[EventType]:
        return [e.type for e in self.timeline(run_id)]


class AuditProjection:
    """Trilha imutável quem-fez-o-quê / negações (ADR-005 audit central)."""

    AUDIT_TYPES = frozenset({
        EventType.APPROVAL_GRANTED, EventType.APPROVAL_DENIED, EventType.POLICY_DENIED,
        EventType.RISK_REJECTED, EventType.CAPABILITY_INVOKED, EventType.DEPLOYMENT_COMPLETED,
    })

    def __init__(self) -> None:
        self.trail: list[dict] = []

    def apply(self, event: Event) -> None:
        if event.type in self.AUDIT_TYPES:
            self.trail.append({
                "event_id": event.id, "type": event.type.value, "time": event.time,
                "tenant_id": event.tenant_id, "run_id": event.correlation_id,
                "actor": event.data.get("actor"), "subject": event.subject,
                "detail": event.data,
            })

    def denials(self) -> list[dict]:
        return [r for r in self.trail
                if r["type"] in ("com.dataforall.policy.denied", "com.dataforall.risk.rejected")]


class EventConsumer:
    """Alimenta N projeções, deduplicando por `event.id` (D12.7)."""

    def __init__(self, projections: list[Projection]) -> None:
        self._projections = projections
        self._seen: set[str] = set()

    def consume(self, event: Event) -> bool:
        """Aplica o evento às projeções. Retorna False se já visto (dedup)."""
        if event.id in self._seen:
            return False
        self._seen.add(event.id)
        for p in self._projections:
            p.apply(event)
        return True

    def consume_dict(self, envelope: dict) -> bool:
        """Consome um envelope serializado (value do Kafka)."""
        return self.consume(Event.from_dict(envelope))

    def run_kafka(self, topics: list[str], bootstrap_servers: str, *,
                  group_id: str, max_messages: int | None = None) -> int:
        """Loop de consumo real (opt-in; lazy import). Decodifica o value JSON e
        alimenta as projeções, deduplicando por id. Retorna nº de eventos aplicados."""
        try:
            import json
            from kafka import KafkaConsumer  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("run_kafka requer 'kafka-python'") from e
        consumer = KafkaConsumer(*topics, bootstrap_servers=bootstrap_servers,
                                 group_id=group_id, enable_auto_commit=True,
                                 auto_offset_reset="earliest",
                                 value_deserializer=lambda b: json.loads(b.decode("utf-8")))
        applied = 0
        for msg in consumer:
            if self.consume_dict(msg.value):
                applied += 1
            if max_messages is not None and applied >= max_messages:
                break
        consumer.close()
        return applied
