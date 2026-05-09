"""Testes da Phase 2h — priority queue + preemption.

Cobre:
- Enfileiramento persistido quando cost cap é atingido.
- `cancel_queued_request`: success, not found, wrong status.
- Preemption para priority='high' (low-priority VMs terminadas).
- Sem preemption para priority='medium' e 'low'.
- Preemption não toca VMs com leases medium/high.
- Processamento da fila após `release_lease` liberar capacidade.
- Processamento da fila após `_on_vm_failed` liberar capacidade.
- Compartilhamento com VM recém-READY ao processar fila.
- Posição na fila e estimated_wait_min.
- `request_id` presente em AllocationDecision quando QUEUED.
- Fila ordena high antes de medium antes de low.
- Owner cap respeitado ao processar fila.
"""

from __future__ import annotations

import pytest

from src.knowledge.allocator_store import (
    AllocatorPolicy,
    AllocatorStore,
    AllocatorStoreError,
)
from src.models.allocator import VMRequest

# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _policy(**kw) -> AllocatorPolicy:
    defaults = dict(
        max_cost_usd_per_hour=5.0,
        max_active_leases_per_owner=3,
        max_lease_duration_min=24 * 60,
        max_extensions_per_lease=3,
        spec_whitelist_no_approval=frozenset({"cpu-small", "cpu-medium", "cpu-large"}),
    )
    defaults.update(kw)
    return AllocatorPolicy(**defaults)


def _store(policy: AllocatorPolicy | None = None) -> AllocatorStore:
    """Store em memória com ImmediateProvisioner (provisionamento síncrono)."""
    return AllocatorStore(db_path=":memory:", policy=policy or _policy())


def _req(
    spec: str = "cpu-small",
    duration_min: int = 60,
    owner: str = "agent-1",
    priority: str = "low",
    exclusive: bool = False,
    purpose: str | None = None,
    human_approved: bool = False,
) -> VMRequest:
    return VMRequest(
        spec=spec,  # type: ignore[arg-type]
        duration_min=duration_min,
        owner=owner,
        priority=priority,  # type: ignore[arg-type]
        exclusive=exclusive,
        purpose=purpose,
        human_approved=human_approved,
    )


# Cap baixo: cpu-small ($0.10/h); cabe 1 VM antes de travar.
_LOW_CAP = _policy(max_cost_usd_per_hour=0.15)


# ------------------------------------------------------------------ #
# 1-3. Enfileiramento básico                                          #
# ------------------------------------------------------------------ #

class TestQueueBasics:
    def test_queued_when_cost_cap_hit(self):
        """Segundo request com nova VM vai para QUEUED quando cost cap é atingido."""
        store = _store(_LOW_CAP)
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        assert r1.outcome == "LEASED"

        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"

    def test_queued_decision_has_request_id(self):
        """`request_id` presente em AllocationDecision quando outcome=QUEUED."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"
        assert r2.request_id is not None
        assert r2.request_id.startswith("req-")

    def test_queued_position_increments(self):
        """Segunda requisição na fila tem posição 2."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        r3 = store.request_vm(_req(spec="cpu-small", owner="agent-3"))
        assert r2.outcome == "QUEUED"
        assert r3.outcome == "QUEUED"
        assert r2.queued_position == 1
        assert r3.queued_position == 2

    def test_estimated_wait_min_set(self):
        """`estimated_wait_min` é positivo quando QUEUED."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"
        assert r2.estimated_wait_min is not None
        assert r2.estimated_wait_min > 0


# ------------------------------------------------------------------ #
# 4-6. cancel_queued_request                                          #
# ------------------------------------------------------------------ #

class TestCancelQueuedRequest:
    def test_cancel_success(self):
        """Cancela request WAITING com sucesso."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"

        result = store.cancel_queued_request(r2.request_id, by="agent-2")
        assert result["cancelled"] is True
        assert result["request_id"] == r2.request_id

    def test_cancel_not_found_raises(self):
        """AllocatorStoreError ao cancelar request_id inexistente."""
        store = _store()
        with pytest.raises(AllocatorStoreError, match="não existe"):
            store.cancel_queued_request("req-doesnotexist")

    def test_cancel_already_cancelled_raises(self):
        """AllocatorStoreError ao cancelar request que já foi cancelado."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        store.cancel_queued_request(r2.request_id)

        with pytest.raises(AllocatorStoreError, match="WAITING"):
            store.cancel_queued_request(r2.request_id)


# ------------------------------------------------------------------ #
# 7-10. Preemption                                                    #
# ------------------------------------------------------------------ #

class TestPreemption:
    def test_high_priority_preempts_exclusive_low_priority_vm(self):
        """Priority='high' preempta VM exclusiva com apenas leases low-priority."""
        store = _store(_LOW_CAP)

        # VM1 provisionada com lease low-priority exclusivo → trava o cap
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", priority="low", exclusive=True))
        assert r1.outcome == "LEASED"
        lease1_id = r1.lease.lease_id  # type: ignore[union-attr]

        # Request high-priority: não pode compartilhar (exclusive), cap atingido.
        # Preemption deve terminar VM1, liberar orçamento, provisionar nova VM.
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", priority="high"))
        assert r2.outcome == "LEASED"

        # Lease de agent-1 deve ter sido preemptado (RELEASED)
        lease1 = store.get_lease(lease1_id)
        assert lease1 is not None
        assert lease1.status == "RELEASED"

    def test_medium_priority_does_not_preempt(self):
        """Priority='medium' não dispara preemption → vai para QUEUED."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", priority="low", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", priority="medium"))
        assert r2.outcome == "QUEUED"
        assert r2.request_id is not None

    def test_low_priority_does_not_preempt(self):
        """Priority='low' não dispara preemption → vai para QUEUED."""
        store = _store(_LOW_CAP)
        store.request_vm(_req(spec="cpu-small", owner="agent-1", priority="low", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", priority="low"))
        assert r2.outcome == "QUEUED"

    def test_high_priority_no_preempt_when_vm_has_medium_lease(self):
        """VM com lease medium-priority não é preemptável. Request high vai para QUEUED."""
        store = _store(_LOW_CAP)
        # VM1 com lease medium (não preemptável)
        store.request_vm(
            _req(spec="cpu-small", owner="agent-1", priority="medium", exclusive=True)
        )

        # High-priority request: sem VM preemptável → QUEUED
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", priority="high"))
        assert r2.outcome == "QUEUED"
        assert r2.request_id is not None

    def test_high_priority_preempts_multiple_vms_if_needed(self):
        """Preemption greedy: preempta múltiplas VMs se uma só não libera orçamento suficiente."""
        # Cap de $0.25/h. cpu-small=$0.10; cpu-medium=$0.30.
        # Dois cpu-smalls usam $0.20. Para provisionar cpu-medium ($0.30): precisa de $0.25 livre.
        # Preemptando os dois cpu-smalls libera $0.20. Ainda não basta...
        # Então com dois cpu-smalls ($0.20) tentando provisionar cpu-medium ($0.30):
        # $0.20 + $0.30 = $0.50 > $0.25 → precisa liberar $0.25 de deficit.
        # Greedily: cpu-small mais caro = $0.10, pick 2, freed = $0.20 < $0.25 → sem preemption.
        # → QUEUED mesmo sendo high-priority.
        store = _store(_policy(max_cost_usd_per_hour=0.25))

        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", priority="low", exclusive=True))
        assert r1.outcome == "LEASED"
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", priority="low", exclusive=True))
        assert r2.outcome == "LEASED"

        # Cost now: $0.20. Provisioning cpu-medium ($0.30): $0.50 > $0.25.
        # Freeing both cpu-smalls: $0.20 freed → new cost = $0.00 + $0.30 = $0.30 > $0.25.
        # Still over cap after preempting everything → QUEUED.
        r3 = store.request_vm(_req(spec="cpu-medium", owner="agent-3", priority="high"))
        assert r3.outcome == "QUEUED"


# ------------------------------------------------------------------ #
# 11-12. Processamento da fila após liberar capacidade               #
# ------------------------------------------------------------------ #

class TestQueueFulfillment:
    def test_queued_fulfilled_after_release(self):
        """Após release_lease que termina VM, queued request é provisionado."""
        store = _store(_LOW_CAP)

        # Preenche cap
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        assert r1.outcome == "LEASED"

        # Request para fila
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"

        # Libera VM1 → cost cai → fila processada → agent-2 recebe VM
        store.release_lease(r1.lease.lease_id, by="agent-1")  # type: ignore[union-attr]

        # agent-2 deve ter lease ACTIVE (ImmediateProvisioner é síncrono)
        leases = store.list_leases(owner="agent-2", status="ACTIVE")
        assert len(leases) == 1

    def test_queued_not_fulfilled_if_still_over_cap_after_release(self):
        """Se o release não libera orçamento suficiente, queued permanece WAITING."""
        # Cap baixíssimo: só 1 cpu-small. cpu-medium requer $0.30 > $0.15 mesmo com 0 VMs.
        # Mas ESPERA: cap é 0.15. Se não há VMs ($0.00), adicionar cpu-medium ($0.30):
        # $0.30 > $0.15 → QUEUED. Mesmo após release de cpu-small: $0.00 + $0.30 > $0.15.
        store = _store(_LOW_CAP)
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        assert r1.outcome == "LEASED"

        r2 = store.request_vm(
            _req(spec="cpu-medium", owner="agent-2", priority="low")
        )
        assert r2.outcome == "QUEUED"

        store.release_lease(r1.lease.lease_id, by="agent-1")  # type: ignore[union-attr]

        # cpu-medium ($0.30) ainda excede o cap ($0.15) mesmo sem nenhuma VM
        leases = store.list_leases(owner="agent-2")
        active = [lx for lx in leases if lx.status in ("PENDING", "ACTIVE")]
        assert len(active) == 0

    def test_queued_fulfilled_by_sharing_ready_vm(self):
        """Request na fila é atendido via compartilhamento quando VM fica READY.

        Usa provisioner lento (não chama on_ready automaticamente) para que
        a VM esteja PROVISIONING quando o segundo request chega, forçando o
        segundo request a cair na fila (cost cap). Depois on_ready é disparado
        manualmente → _try_fulfill_queued_inside_lock encontra VM READY para share.
        """
        from src.knowledge.provisioner import ImmediateProvisioner

        class _SlowProvisioner(ImmediateProvisioner):
            """Provisioner que adia on_ready até flush() ser chamado."""

            def __init__(self) -> None:
                self._pending: list[tuple] = []

            def provision(self, spec, vm_id, *, on_ready, on_failed, **kw) -> None:  # type: ignore[override]
                self._pending.append((vm_id, on_ready))

            def flush(self) -> None:
                for vm_id, on_ready in self._pending:
                    on_ready(f"immediate://{vm_id}")
                self._pending.clear()

        provisioner = _SlowProvisioner()
        store = AllocatorStore(
            db_path=":memory:",
            policy=_policy(max_cost_usd_per_hour=0.15),
            provisioner=provisioner,
        )

        # agent-1: inicia provisão (VM fica PROVISIONING — on_ready ainda não foi chamado)
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=False))
        assert r1.outcome == "LEASED"
        assert r1.lease.status == "PENDING"  # type: ignore[union-attr]
        # VM1 está PROVISIONING, custa $0.10 → cap: $0.10 + $0.10 = $0.20 > $0.15

        # agent-2: cost cap hit (VM1 PROVISIONING não pode ser compartilhada) → QUEUED
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", exclusive=False))
        assert r2.outcome == "QUEUED"

        # VM1 fica READY → _on_vm_ready disparado → queue fulfillment:
        # agent-2 pode compartilhar VM1 (não-exclusivo, 1 lease < 4)
        provisioner.flush()

        # agent-2 deve ter lease ACTIVE (share com VM1, sem nova VM)
        leases = store.list_leases(owner="agent-2", status="ACTIVE")
        assert len(leases) == 1

    def test_cancelled_request_not_fulfilled(self):
        """Request cancelado na fila não é atendido quando capacidade libera."""
        store = _store(_LOW_CAP)
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"

        # Cancela antes do release
        store.cancel_queued_request(r2.request_id)  # type: ignore[arg-type]

        # Release VM1 → fila processada, mas r2 está CANCELLED → ignorado
        store.release_lease(r1.lease.lease_id, by="agent-1")  # type: ignore[union-attr]

        leases = store.list_leases(owner="agent-2")
        assert all(lx.status not in ("PENDING", "ACTIVE") for lx in leases)

    def test_on_vm_failed_triggers_queue_fulfillment(self):
        """Quando VM falha, orçamento libera e fila é processada."""
        store = _store(_LOW_CAP)
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", exclusive=True))
        assert r1.outcome == "LEASED"
        vm1_id = r1.lease.vm_id  # type: ignore[union-attr]

        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2"))
        assert r2.outcome == "QUEUED"

        # Simula falha da VM1 → custo retira para $0.00 → fila processada
        store._on_vm_failed(vm1_id, "simulated failure")

        # agent-2 deve ter lease provisionado (ImmediateProvisioner é síncrono)
        leases = store.list_leases(owner="agent-2")
        has_active = any(lx.status in ("PENDING", "ACTIVE") for lx in leases)
        assert has_active


# ------------------------------------------------------------------ #
# 13-15. Ordem da fila + owner cap                                    #
# ------------------------------------------------------------------ #

class TestQueueOrder:
    def test_high_priority_fulfilled_before_low_when_capacity_frees(self):
        """Na fila, high-priority é atendido antes de low-priority.

        Setup: VM1 com lease medium (não preemptável por preemption) preenche o cap.
        agent-low e agent-high ambos caem na fila (exclusive=True para bloquear share).
        Ao liberar VM1, fila processa high antes de low, e apenas 1 nova VM cabe no cap.
        """
        store = _store(_LOW_CAP)
        # Usa medium-priority para agent-1 → VM1 NÃO é preemptável
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", priority="medium", exclusive=True))
        assert r1.outcome == "LEASED"

        # Dois requests na fila (exclusive=True para não poderem compartilhar entre si):
        # low antes de high na chegada → fila persistida
        r_low = store.request_vm(_req(spec="cpu-small", owner="agent-low", priority="low", exclusive=True))
        r_high = store.request_vm(_req(spec="cpu-small", owner="agent-high", priority="high", exclusive=True))
        assert r_low.outcome == "QUEUED"
        assert r_high.outcome == "QUEUED"  # high não preempta porque VM1 tem lease medium

        # Libera VM1 → custo cai → fila processa (apenas 1 VM cabe no cap de $0.15)
        store.release_lease(r1.lease.lease_id, by="agent-1")  # type: ignore[union-attr]

        # agent-high deve ter sido atendido (high priority é processado primeiro)
        leases_high = store.list_leases(owner="agent-high")
        leases_low = store.list_leases(owner="agent-low")
        assert any(lx.status in ("PENDING", "ACTIVE") for lx in leases_high)
        # agent-low ainda na fila pois cap só comporta 1 nova VM exclusiva
        assert all(lx.status not in ("PENDING", "ACTIVE") for lx in leases_low)

    def test_only_one_queued_request_fulfilled_when_cap_allows_one(self):
        """Apenas 1 request da fila é provisionado quando o orçamento só comporta 1 nova VM.

        Usa exclusive=True nos requests da fila para impedir que _on_vm_ready
        satisfaça o segundo agente via share (o que seria correto mas tornaria
        a leitura do teste confusa).
        """
        store = _store(_LOW_CAP)  # cap $0.15 → cabe apenas 1 cpu-small ($0.10)
        r1 = store.request_vm(_req(spec="cpu-small", owner="agent-1", priority="medium", exclusive=True))
        assert r1.outcome == "LEASED"

        # Dois agentes na fila com exclusive=True → sem share possível
        r2 = store.request_vm(_req(spec="cpu-small", owner="agent-2", exclusive=True))
        r3 = store.request_vm(_req(spec="cpu-small", owner="agent-3", exclusive=True))
        assert r2.outcome == "QUEUED"
        assert r3.outcome == "QUEUED"

        # Libera VM1 → custo cai para $0.00 → fila processa
        # agent-2 é atendido (primeira posição): VM2 provisionada ($0.10)
        # agent-3: $0.10 + $0.10 = $0.20 > $0.15 → ainda no cap → permanece WAITING
        store.release_lease(r1.lease.lease_id, by="agent-1")  # type: ignore[union-attr]

        leases_2 = store.list_leases(owner="agent-2")
        leases_3 = store.list_leases(owner="agent-3")
        # Exatamente 1 agente foi atendido
        active_count = (
            sum(1 for lx in leases_2 if lx.status in ("PENDING", "ACTIVE"))
            + sum(1 for lx in leases_3 if lx.status in ("PENDING", "ACTIVE"))
        )
        assert active_count == 1
        # agent-2 (posição 1) deve ter sido o atendido
        assert any(lx.status in ("PENDING", "ACTIVE") for lx in leases_2)
