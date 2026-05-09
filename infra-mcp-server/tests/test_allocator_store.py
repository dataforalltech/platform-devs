"""Testes do AllocatorStore — pure logic, sem subprocess.

Cobre:
- Strategy: try-share-first → provision-if-budget → queue-or-deny
- Hard stops: cost cap, concurrent leases por owner, spec whitelist,
  duration cap, max extensions
- Lifecycle: lease ACTIVE → RELEASED → VM TERMINATED quando órfã
- GC: leases expirados marcam EXPIRED em _gc_expired
- Sharing: exclusive lock impede outros leases na mesma VM
- Idempotência: release de lease já liberado é no-op
- query_capacity: blocked_by motivo correto
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.knowledge.allocator_store import (
    AllocatorPolicy,
    AllocatorStore,
    AllocatorStoreError,
    LeaseNotFound,
)
from src.models.allocator import VMRequest, now_utc


def _req(
    spec: str = "cpu-small",
    duration_min: int = 60,
    owner: str = "agent-x",
    exclusive: bool = False,
    priority: str = "low",
    human_approved: bool = False,
) -> VMRequest:
    return VMRequest(
        spec=spec,  # type: ignore[arg-type]
        duration_min=duration_min,
        owner=owner,
        exclusive=exclusive,
        priority=priority,  # type: ignore[arg-type]
        human_approved=human_approved,
    )


# --------------------------- happy path --------------------------- #
def test_first_request_provisions_new_vm():
    store = AllocatorStore()
    decision = store.request_vm(_req())
    assert decision.outcome == "LEASED"
    assert decision.lease is not None
    assert decision.lease.status == "ACTIVE"
    assert decision.lease.spec == "cpu-small"
    assert decision.lease.connection_hint is not None


def test_second_compatible_request_shares_vm():
    store = AllocatorStore()
    d1 = store.request_vm(_req(owner="a"))
    d2 = store.request_vm(_req(owner="b"))
    assert d1.outcome == "LEASED"
    assert d2.outcome == "LEASED"
    assert d1.lease.vm_id == d2.lease.vm_id  # shared
    pool = store.list_pool()
    assert len(pool.vms) == 1


def test_exclusive_request_does_not_share():
    store = AllocatorStore()
    d1 = store.request_vm(_req(owner="a"))
    d2 = store.request_vm(_req(owner="b", exclusive=True))
    assert d1.lease.vm_id != d2.lease.vm_id
    pool = store.list_pool()
    assert len(pool.vms) == 2


def test_request_after_exclusive_lock_does_not_share():
    """VM exclusive-locked não aceita novos leases mesmo de outro agente."""
    store = AllocatorStore()
    d_exclusive = store.request_vm(_req(owner="a", exclusive=True))
    d_other = store.request_vm(_req(owner="b"))
    assert d_other.lease.vm_id != d_exclusive.lease.vm_id


# --------------------------- hard stops --------------------------- #
def test_gpu_a100_denied_without_human_approval():
    store = AllocatorStore()
    d = store.request_vm(_req(spec="gpu-a100", human_approved=False))
    assert d.outcome == "DENIED"
    assert "aprovação humana" in d.denial_reason


def test_gpu_a100_allowed_with_human_approval():
    store = AllocatorStore(
        # cap suficiente p/ provision de gpu-a100 ($4/h)
        policy=AllocatorPolicy(max_cost_usd_per_hour=10.0)
    )
    d = store.request_vm(_req(spec="gpu-a100", human_approved=True))
    assert d.outcome == "LEASED"


def test_high_mem_denied_without_human_approval():
    store = AllocatorStore()
    d = store.request_vm(_req(spec="high-mem", human_approved=False))
    assert d.outcome == "DENIED"


def test_concurrent_lease_cap_per_owner():
    store = AllocatorStore(
        policy=AllocatorPolicy(max_active_leases_per_owner=2, max_cost_usd_per_hour=100.0)
    )
    store.request_vm(_req(owner="a", exclusive=True))  # vm 1
    store.request_vm(_req(owner="a", exclusive=True))  # vm 2
    d3 = store.request_vm(_req(owner="a", exclusive=True))
    assert d3.outcome == "DENIED"
    assert "leases ativos" in d3.denial_reason


def test_duration_cap_enforced():
    store = AllocatorStore(policy=AllocatorPolicy(max_lease_duration_min=120))
    d = store.request_vm(_req(duration_min=200))
    assert d.outcome == "DENIED"
    assert "duration_min" in d.denial_reason


def test_cost_cap_queues_request():
    """Pool atinge cap → próxima request fica QUEUED."""
    # Cap baixo: ~3.5 cpu-smalls a $0.10 = $0.35 dentro de cap $0.30 não cabe.
    store = AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=0.20))
    d1 = store.request_vm(_req(owner="a", exclusive=True))  # provisions vm1, cost=0.10
    assert d1.outcome == "LEASED"
    d2 = store.request_vm(_req(owner="b", exclusive=True))  # provisions vm2, cost=0.20
    assert d2.outcome == "LEASED"
    d3 = store.request_vm(_req(owner="c", exclusive=True))  # would be 0.30, > 0.20 cap
    assert d3.outcome == "QUEUED"
    assert d3.queued_position == 1


# --------------------------- release / extend --------------------------- #
def test_release_marks_lease_released_and_terminates_orphan_vm():
    store = AllocatorStore()
    d = store.request_vm(_req())
    lease_id = d.lease.lease_id
    vm_id = d.lease.vm_id
    released = store.release_lease(lease_id, by="user")
    assert released.status == "RELEASED"
    assert released.released_at is not None
    pool = store.list_pool()
    # VM órfã foi terminada
    assert all(vm.vm_id != vm_id for vm in pool.vms)


def test_release_unknown_lease_raises():
    store = AllocatorStore()
    with pytest.raises(LeaseNotFound):
        store.release_lease("lease-nonexistent")


def test_release_is_idempotent():
    store = AllocatorStore()
    d = store.request_vm(_req())
    lease_id = d.lease.lease_id
    store.release_lease(lease_id)
    # Segundo release não levanta — devolve estado atual
    again = store.release_lease(lease_id)
    assert again.status == "RELEASED"


def test_extend_lease_bumps_expiry():
    store = AllocatorStore()
    d = store.request_vm(_req(duration_min=30))
    initial_expiry = d.lease.expires_at
    extended = store.extend_lease(d.lease.lease_id, additional_min=30)
    assert extended.expires_at == initial_expiry + timedelta(minutes=30)
    assert extended.extension_count == 1


def test_extend_caps_at_max_extensions():
    store = AllocatorStore(
        policy=AllocatorPolicy(max_extensions_per_lease=2, max_lease_duration_min=24 * 60)
    )
    d = store.request_vm(_req(duration_min=10))
    lease_id = d.lease.lease_id
    store.extend_lease(lease_id, 5)
    store.extend_lease(lease_id, 5)
    with pytest.raises(AllocatorStoreError, match="max_extensions"):
        store.extend_lease(lease_id, 5)


def test_extend_caps_at_total_duration():
    store = AllocatorStore(policy=AllocatorPolicy(max_lease_duration_min=60))
    d = store.request_vm(_req(duration_min=30))
    with pytest.raises(AllocatorStoreError, match="exceder cap"):
        store.extend_lease(d.lease.lease_id, additional_min=60)


def test_extend_with_zero_or_negative_min_raises():
    store = AllocatorStore()
    d = store.request_vm(_req())
    with pytest.raises(AllocatorStoreError):
        store.extend_lease(d.lease.lease_id, 0)
    with pytest.raises(AllocatorStoreError):
        store.extend_lease(d.lease.lease_id, -10)


def test_extend_unknown_lease_raises():
    store = AllocatorStore()
    with pytest.raises(LeaseNotFound):
        store.extend_lease("lease-bogus", 10)


def test_cannot_extend_released_lease():
    store = AllocatorStore()
    d = store.request_vm(_req())
    store.release_lease(d.lease.lease_id)
    with pytest.raises(AllocatorStoreError):
        store.extend_lease(d.lease.lease_id, 10)


# --------------------------- listing --------------------------- #
def test_list_my_leases_filters_by_owner():
    store = AllocatorStore()
    store.request_vm(_req(owner="a"))
    store.request_vm(_req(owner="b"))
    store.request_vm(_req(owner="a"))
    leases_a = store.list_leases(owner="a")
    assert len(leases_a) == 2
    assert all(lease.owner == "a" for lease in leases_a)


def test_list_my_leases_filters_by_status():
    store = AllocatorStore()
    d1 = store.request_vm(_req(owner="a"))
    store.request_vm(_req(owner="a"))
    store.release_lease(d1.lease.lease_id)
    active = store.list_leases(owner="a", status="ACTIVE")
    released = store.list_leases(owner="a", status="RELEASED")
    assert len(active) == 1
    assert len(released) == 1


def test_list_pool_reports_total_cost():
    store = AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=100.0))
    store.request_vm(_req(spec="cpu-small", exclusive=True, owner="a"))  # 0.10
    store.request_vm(_req(spec="cpu-medium", exclusive=True, owner="b"))  # 0.30
    snapshot = store.list_pool()
    assert len(snapshot.vms) == 2
    assert snapshot.total_provisioned_cost_usd_per_hour == pytest.approx(0.40, abs=0.01)


# --------------------------- query_capacity --------------------------- #
def test_capacity_satisfied_by_existing_vm():
    store = AllocatorStore()
    store.request_vm(_req())  # provisions cpu-small
    cap = store.query_capacity("cpu-small")
    assert cap.can_satisfy_now is True
    assert cap.by_existing_vm is True
    assert cap.would_provision is False


def test_capacity_would_provision_if_no_match():
    store = AllocatorStore()
    cap = store.query_capacity("cpu-small")
    assert cap.can_satisfy_now is True
    assert cap.would_provision is True


def test_capacity_blocked_by_approval():
    store = AllocatorStore()
    cap = store.query_capacity("gpu-a100")
    assert cap.can_satisfy_now is False
    assert cap.blocked_by == "approval_required"


def test_capacity_blocked_by_owner_concurrent_cap():
    store = AllocatorStore(
        policy=AllocatorPolicy(max_active_leases_per_owner=1, max_cost_usd_per_hour=100.0)
    )
    store.request_vm(_req(owner="a", exclusive=True))
    cap = store.query_capacity("cpu-small", owner="a")
    assert cap.can_satisfy_now is False
    assert cap.blocked_by == "owner_concurrent_lease_cap"


def test_capacity_blocked_by_cost_cap():
    store = AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=0.05))
    cap = store.query_capacity("cpu-small")  # 0.10 > 0.05
    assert cap.can_satisfy_now is False
    assert cap.blocked_by == "cost_cap"


# --------------------------- GC of expired leases --------------------------- #
def test_expired_lease_marked_on_next_operation(monkeypatch):
    """Lease com expires_at no passado vira EXPIRED no próximo gc tick."""
    store = AllocatorStore()
    d = store.request_vm(_req(duration_min=1))
    lease_id = d.lease.lease_id

    # Avança "tempo" forçando expires_at para o passado diretamente no SQLite.
    past = (now_utc() - timedelta(minutes=1)).isoformat()
    store._con.execute(
        "UPDATE leases SET expires_at=? WHERE lease_id=?",
        (past, lease_id),
    )

    # Próxima operação dispara _gc_expired
    fetched = store.get_lease(lease_id)
    assert fetched is not None
    assert fetched.status == "EXPIRED"
    # VM órfã foi terminada
    pool = store.list_pool()
    assert len(pool.vms) == 0


# --------------------------- compatible VM matching --------------------------- #
def test_different_spec_does_not_share_vm():
    store = AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=100.0))
    d1 = store.request_vm(_req(spec="cpu-small", owner="a"))
    d2 = store.request_vm(_req(spec="cpu-medium", owner="b"))
    assert d1.lease.vm_id != d2.lease.vm_id


def test_n_leases_share_until_capacity_cap():
    """has_capacity_for limita a 4 leases por VM (Phase 2a)."""
    store = AllocatorStore(
        policy=AllocatorPolicy(max_active_leases_per_owner=10, max_cost_usd_per_hour=100.0)
    )
    leases = []
    for i in range(5):  # 5ª deveria criar VM nova
        d = store.request_vm(_req(owner=f"a{i}"))
        leases.append(d.lease)
    pool = store.list_pool()
    # 4 compartilharam vm1, 5ª criou vm2
    assert len(pool.vms) == 2
