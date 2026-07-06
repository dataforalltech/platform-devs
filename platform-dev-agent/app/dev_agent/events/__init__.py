"""Fase 4 — Event Model canônico (ADR-012): envelope CloudEvents + sinks + emitter."""

from app.dev_agent.events.emitter import EventEmitter
from app.dev_agent.events.model import (
    TOPIC_BY_TYPE, Event, EventType, new_ulid,
)
from app.dev_agent.events.sink import (
    EventSink, InMemoryEventSink, KafkaEventSink, LoggingEventSink, NullEventSink,
)

__all__ = [
    "Event", "EventType", "TOPIC_BY_TYPE", "new_ulid", "EventEmitter",
    "EventSink", "InMemoryEventSink", "LoggingEventSink", "NullEventSink", "KafkaEventSink",
]
