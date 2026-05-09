"""Modelos do VM allocator (Phase 2a — in-memory).

Domínio:

  VMSpec       — tipo de recurso (catálogo fechado e versionado)
  VMRequest    — pedido do agente
  VMLease      — concessão (slot atribuído ao agente, com TTL)
  VMInfo       — VM no pool (id, spec, status, leases)
  VMPool       — inventário inteiro
  AllocationDecision — resultado de um request_vm: lease | queued | denied

Estados:

  Lease:  PENDING (provisionando) -> ACTIVE -> RELEASED | EXPIRED
  VM:     PROVISIONING -> READY -> DRAINING -> TERMINATED

Phase 2a NÃO provisiona infra real. VMs são simuladas em memória — o `vm_id`
identifica entradas no pool sem corresponder a recursos Azure. Quando
chegarmos em Phase 2c, `provision_vm()` chama terraform_apply via Phase 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------- #
# Catálogo de specs (fechado e versionado)                              #
# --------------------------------------------------------------------- #
# Specs com escala de risco/custo crescente. Specs novas exigem ADR.
VMSpecName = Literal[
    "cpu-small",   # ~2 vCPU / 4 GB — baixo custo, default p/ tarefas leves
    "cpu-medium",  # ~4 vCPU / 16 GB
    "cpu-large",   # ~8 vCPU / 32 GB
    "high-mem",    # ~4 vCPU / 64 GB — caro
    "gpu-a100",    # exige aprovação humana out-of-band
]

# Specs que SEMPRE exigem aprovação humana — request_vm com elas vai para
# DENIED com motivo "approval_required" se vier de agente automático sem flag
# `human_approved=True` no request.
HUMAN_APPROVAL_REQUIRED_SPECS: frozenset[str] = frozenset({"gpu-a100", "high-mem"})

# Custo aproximado por hora em USD — usado para cost cap. Phase 2a usa números
# fixos; Phase 2c integra com infracost real.
SPEC_COST_USD_PER_HOUR: dict[str, float] = {
    "cpu-small": 0.10,
    "cpu-medium": 0.30,
    "cpu-large": 0.80,
    "high-mem": 1.50,
    "gpu-a100": 4.00,
}

LeaseStatus = Literal["PENDING", "ACTIVE", "RELEASED", "EXPIRED"]
VMStatus = Literal["PROVISIONING", "READY", "DRAINING", "TERMINATED"]
Priority = Literal["low", "medium", "high"]
AllocationOutcome = Literal["LEASED", "QUEUED", "DENIED"]


# --------------------------------------------------------------------- #
# Request / Lease / VM                                                  #
# --------------------------------------------------------------------- #
class VMRequest(BaseModel):
    """Pedido do agente."""

    spec: VMSpecName
    duration_min: int = Field(
        ge=1,
        le=72 * 60,  # cap absoluto: 72h
        description="Duração estimada em minutos. Cap absoluto 72h (Phase 2a).",
    )
    exclusive: bool = Field(
        default=False,
        description="True = não compartilhar a VM com outras workloads.",
    )
    priority: Priority = "low"
    owner: str = Field(description="Identificador do agente solicitante.")
    purpose: str | None = Field(
        default=None,
        description="Descrição curta para audit (ex.: 'training-job-x').",
    )
    human_approved: bool = Field(
        default=False,
        description=(
            "Marca True somente quando humano aprovou out-of-band para specs "
            "que exigem aprovação (ver HUMAN_APPROVAL_REQUIRED_SPECS)."
        ),
    )

    @field_validator("owner")
    @classmethod
    def _owner_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("owner é obrigatório")
        return v.strip()


class VMLease(BaseModel):
    """Concessão de slot a um agente."""

    lease_id: str
    vm_id: str
    spec: VMSpecName
    owner: str
    purpose: str | None = None
    status: LeaseStatus = "PENDING"
    exclusive: bool = False
    priority: Priority = "low"
    created_at: datetime
    expires_at: datetime
    released_at: datetime | None = None
    extension_count: int = 0
    connection_hint: str | None = Field(
        default=None,
        description=(
            "Phase 2a: simulado (None ou string mock). "
            "Phase 2c: contém endpoint/IP + ssh key reference."
        ),
    )

    def is_active_at(self, now: datetime) -> bool:
        return self.status == "ACTIVE" and now < self.expires_at

    def remaining_min(self, now: datetime) -> int:
        if self.status not in ("PENDING", "ACTIVE"):
            return 0
        delta = (self.expires_at - now).total_seconds() / 60.0
        return max(0, int(delta))


class VMInfo(BaseModel):
    """Uma VM no pool (Phase 2a: simulada)."""

    vm_id: str
    spec: VMSpecName
    status: VMStatus = "READY"
    created_at: datetime
    lease_ids: list[str] = Field(default_factory=list)
    exclusive_locked_by: str | None = Field(
        default=None,
        description="lease_id que tem exclusividade (se houver).",
    )

    def has_capacity_for(self, request: VMRequest) -> bool:
        """Decide se essa VM pode acomodar mais um lease.

        Regras Phase 2a:
        - Se já tem lease exclusivo → não aceita mais ninguém.
        - Se request é exclusivo → não aceita se já tem qualquer lease.
        - Senão → cap simples de N=4 leases concorrentes (limite empírico).
        """
        if self.status != "READY":
            return False
        if self.spec != request.spec:
            return False
        if self.exclusive_locked_by:
            return False
        if request.exclusive and self.lease_ids:
            return False
        return len(self.lease_ids) < 4


# --------------------------------------------------------------------- #
# Pool snapshot                                                          #
# --------------------------------------------------------------------- #
class VMPoolSnapshot(BaseModel):
    """Estado agregado do pool em um instante."""

    vms: list[VMInfo]
    active_lease_count: int
    total_provisioned_cost_usd_per_hour: float


# --------------------------------------------------------------------- #
# Resposta de allocate                                                   #
# --------------------------------------------------------------------- #
class AllocationDecision(BaseModel):
    """Resultado de um request_vm.

    `outcome=LEASED` → `lease` populado.
    `outcome=QUEUED` → `queued_position`, `estimated_wait_min` e `request_id` populados.
    `outcome=DENIED` → `denial_reason` populado.

    Phase 2h: `request_id` identifica a posição na fila persistida (SQLite).
    Use `cancel_queued_request(request_id)` para desistir da fila.
    """

    outcome: AllocationOutcome
    lease: VMLease | None = None
    queued_position: int | None = None
    estimated_wait_min: int | None = None
    request_id: str | None = Field(
        default=None,
        description=(
            "Phase 2h: ID da requisição na fila persistida. "
            "Presente apenas quando outcome=QUEUED. "
            "Use cancel_queued_request(request_id) para desistir."
        ),
    )
    denial_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------- #
# Capacity query                                                         #
# --------------------------------------------------------------------- #
class CapacityResponse(BaseModel):
    """Resposta de query_capacity (planejamento sem efeito)."""

    spec: VMSpecName
    can_satisfy_now: bool
    by_existing_vm: bool
    would_provision: bool
    blocked_by: str | None = Field(
        default=None,
        description="Se can_satisfy_now=False: motivo (cost cap, quota, spec policy).",
    )


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #
def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def lease_expiration(created_at: datetime, duration_min: int) -> datetime:
    return created_at + timedelta(minutes=duration_min)
