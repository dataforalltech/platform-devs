"""Sinks de evento — para onde o envelope vai (ADR-012 D12.5/D12.10).

Pluggable: testes usam InMemory; default local é Logging; produção usa Kafka
(`dataforall-kafka`, :9095). O sink é o ponto único de publicação — o EventEmitter
não sabe de transporte.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from app.dev_agent.events.model import Event

_log = logging.getLogger("dev_agent.events")


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class NullEventSink:
    """Descarta tudo (default seguro quando emissão está desligada)."""

    def emit(self, event: Event) -> None:  # noqa: ARG002
        return None


class InMemoryEventSink:
    """Coleta eventos em ordem (testes / introspecção)."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, t) -> list[Event]:
        return [e for e in self.events if e.type == t]


class LoggingEventSink:
    """Loga o envelope como JSON (default local, sem broker)."""

    def emit(self, event: Event) -> None:
        _log.info("event %s -> %s | %s", event.type.value, event.topic,
                  json.dumps(event.to_dict(), ensure_ascii=False))


class KafkaEventSink:
    """Publica no Kafka (`dataforall-kafka`). Import do produtor é LAZY: sem a lib
    instalada, falha claramente na construção (opt-in). Particiona por tenant_id
    (D12.6); context attrs viram headers, envelope completo vai no value (D12.5).
    """

    def __init__(self, bootstrap_servers: str = "localhost:9095") -> None:
        try:
            from kafka import KafkaProducer  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "KafkaEventSink requer 'kafka-python' (pip install kafka-python). "
                "Use LoggingEventSink/InMemoryEventSink em dev/teste."
            ) from e
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            acks="all",           # durável antes do "sucesso" (D12.7)
        )

    def emit(self, event: Event) -> None:
        self._producer.send(
            event.topic, key=event.partition_key, value=event.to_dict(),
            headers=[(k, v.encode("utf-8")) for k, v in event.headers().items()],
        )
