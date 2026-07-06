"""Fase 4 — Event Model canônico (ADR-012).

Envelope estilo CloudEvents 1.0 + taxonomia de `type`s reverse-DNS + mapa tópico por
*aggregate*. Eventos são FATOS (past tense), imutáveis; `id` é ULID (ordenável, chave de
idempotência do consumidor — D12.7); correlação obrigatória por `tenant_id`/`session_id`/
`correlation_id` (D12.4). O `data` carrega refs/metadados, nunca payload cru (D12.9).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """ULID de 26 chars (48-bit tempo ms + 80-bit aleatório), ordenável no tempo."""
    val = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[val & 0x1F])
        val >>= 5
    return "".join(reversed(out))


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventType(str, Enum):
    """Taxonomia canônica V1 (ADR-012 D12.3), reverse-DNS."""

    PLAN_CREATED = "com.dataforall.plan.created"
    PLAN_APPROVED = "com.dataforall.plan.approved"
    APPROVAL_GRANTED = "com.dataforall.approval.granted"
    APPROVAL_DENIED = "com.dataforall.approval.denied"
    EXECUTION_STARTED = "com.dataforall.execution.started"
    TASK_STARTED = "com.dataforall.task.started"
    TASK_FINISHED = "com.dataforall.task.finished"
    EXECUTION_COMPLETED = "com.dataforall.execution.completed"
    CAPABILITY_INVOKED = "com.dataforall.capability.invoked"
    POLICY_DENIED = "com.dataforall.policy.denied"
    RISK_REJECTED = "com.dataforall.risk.rejected"
    RUNBOOK_COMPLETED = "com.dataforall.runbook.completed"
    DEPLOYMENT_COMPLETED = "com.dataforall.deployment.completed"


# type -> tópico por aggregate (D12.5). Um tópico por aggregate, não por type.
TOPIC_BY_TYPE: dict[EventType, str] = {
    EventType.PLAN_CREATED: "platform.plan.v1",
    EventType.PLAN_APPROVED: "platform.plan.v1",
    EventType.APPROVAL_GRANTED: "platform.approval.v1",
    EventType.APPROVAL_DENIED: "platform.approval.v1",
    EventType.EXECUTION_STARTED: "platform.execution.v1",
    EventType.TASK_STARTED: "platform.execution.v1",
    EventType.TASK_FINISHED: "platform.execution.v1",
    EventType.EXECUTION_COMPLETED: "platform.execution.v1",
    EventType.RUNBOOK_COMPLETED: "platform.execution.v1",
    EventType.CAPABILITY_INVOKED: "platform.capability.v1",
    EventType.POLICY_DENIED: "platform.policy.v1",
    EventType.RISK_REJECTED: "platform.policy.v1",
    EventType.DEPLOYMENT_COMPLETED: "platform.delivery.v1",
}


@dataclass(frozen=True)
class Event:
    """Envelope CloudEvents 1.0 (ADR-012 D12.2)."""

    type: EventType
    subject: str
    data: dict
    # correlação (D12.4)
    tenant_id: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    # context
    source: str = "/platform-dev-agent/runtime"
    id: str = field(default_factory=new_ulid)
    time: str = field(default_factory=_now_rfc3339)
    specversion: str = "1.0"
    datacontenttype: str = "application/json"

    @property
    def topic(self) -> str:
        return TOPIC_BY_TYPE[self.type]

    @property
    def partition_key(self) -> str:
        """Chave de partição = tenant_id (D12.6); fallback estável se ausente."""
        return self.tenant_id or "_system"

    def headers(self) -> dict[str, str]:
        """Context attributes como headers Kafka (indexáveis, D12.5)."""
        h = {"ce_specversion": self.specversion, "ce_id": self.id,
             "ce_type": self.type.value, "ce_source": self.source,
             "ce_subject": self.subject, "ce_time": self.time,
             "correlation_id": self.correlation_id or "", "causation_id": self.causation_id or "",
             "tenant_id": self.tenant_id or ""}
        if self.session_id:
            h["session_id"] = self.session_id
        return h

    def to_dict(self) -> dict:
        """Envelope completo (value do Kafka; self-contained p/ replay)."""
        return {
            "specversion": self.specversion, "id": self.id, "type": self.type.value,
            "source": self.source, "subject": self.subject, "time": self.time,
            "datacontenttype": self.datacontenttype,
            "tenant_id": self.tenant_id, "session_id": self.session_id,
            "correlation_id": self.correlation_id, "causation_id": self.causation_id,
            "data": self.data,
        }
