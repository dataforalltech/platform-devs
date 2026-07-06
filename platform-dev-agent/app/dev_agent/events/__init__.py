"""Fase 4 — Event Model canônico (ADR-012): envelope CloudEvents + sinks + emitter."""

from app.dev_agent.events.consumer import (
    AuditProjection, EventConsumer, Projection, TimelineProjection,
)
from app.dev_agent.events.emitter import EventEmitter
from app.dev_agent.events.model import (
    TOPIC_BY_TYPE, Event, EventType, new_ulid,
)
from app.dev_agent.events.sink import (
    EventSink, InMemoryEventSink, KafkaEventSink, LoggingEventSink, NullEventSink,
)
from app.dev_agent.events.topics import TOPICS, TopicSpec, provision

__all__ = [
    "Event", "EventType", "TOPIC_BY_TYPE", "new_ulid", "EventEmitter",
    "EventSink", "InMemoryEventSink", "LoggingEventSink", "NullEventSink", "KafkaEventSink",
    "EventConsumer", "TimelineProjection", "AuditProjection", "Projection",
    "TOPICS", "TopicSpec", "provision",
]
