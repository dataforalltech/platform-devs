"""AllocatorStore canônico contra MySQL real (§16 / FID-02): ciclo de vida de lease,
compartilhamento, fila (cost cap), preempção, GC, chave SSH e ISOLAMENTO por tenant
(banco-por-tenant). Provisioner = ImmediateProvisioner (lease vira ACTIVE inline)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.db.allocator_store import AllocatorPolicy, AllocatorStoreError, LeaseNotFound, _dt_to_str
from src.models.allocator import VMRequest, now_utc

from .conftest import TENANT_A, TENANT_B, requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


def _req(owner: str = "agent-x", spec: str = "cpu-small", **kw) -> VMRequest:
    return VMRequest(spec=spec, duration_min=kw.pop("duration_min", 60), owner=owner, **kw)


# ── request_vm: lease / share / deny ──────────────────────────────────────────
async def test_request_provisions_and_becomes_active(store_a):
    d = await store_a.request_vm(_req())
    assert d.outcome == "LEASED"
    assert d.lease is not None
    assert d.lease.status == "ACTIVE"  # ImmediateProvisioner
    assert d.lease.vm_id.startswith("vm-")
    assert d.lease.lease_id.startswith("lease-")


async def test_second_request_shares_existing_vm(store_a):
    d1 = await store_a.request_vm(_req(owner="a"))
    d2 = await store_a.request_vm(_req(owner="b"))
    assert d1.lease.vm_id == d2.lease.vm_id  # compartilhado
    assert d2.notes and "compartilhado" in d2.notes[0]


async def test_exclusive_request_does_not_share(store_a):
    d1 = await store_a.request_vm(_req(owner="a"))
    d2 = await store_a.request_vm(_req(owner="b", exclusive=True))
    assert d1.lease.vm_id != d2.lease.vm_id


async def test_denied_when_spec_requires_approval(store_a):
    d = await store_a.request_vm(_req(spec="gpu-a100", human_approved=False))
    assert d.outcome == "DENIED"
    assert "aprovação" in (d.denial_reason or "")


async def test_denied_when_duration_exceeds_cap(make_store):
    store = await make_store(TENANT_A, AllocatorPolicy(max_lease_duration_min=120))
    d = await store.request_vm(_req(duration_min=200))
    assert d.outcome == "DENIED"
    assert "duration_min" in (d.denial_reason or "")


async def test_denied_when_owner_over_concurrent_cap(make_store):
    store = await make_store(
        TENANT_A, AllocatorPolicy(max_active_leases_per_owner=1, max_cost_usd_per_hour=100.0)
    )
    first = await store.request_vm(_req(owner="busy"))
    assert first.outcome == "LEASED"
    second = await store.request_vm(_req(owner="busy", exclusive=True))
    assert second.outcome == "DENIED"
    assert "cap=1" in (second.denial_reason or "")


# ── Fila (cost cap) + cancel ──────────────────────────────────────────────────
async def test_request_queued_when_cost_cap_hit(make_store):
    store = await make_store(TENANT_A, AllocatorPolicy(max_cost_usd_per_hour=0.05))
    d = await store.request_vm(_req())
    assert d.outcome == "QUEUED"
    assert d.request_id and d.request_id.startswith("req-")
    assert d.queued_position == 1


async def test_cancel_queued_request(make_store):
    store = await make_store(TENANT_A, AllocatorPolicy(max_cost_usd_per_hour=0.05))
    d = await store.request_vm(_req())
    res = await store.cancel_queued_request(d.request_id, by="tester")
    assert res == {"cancelled": True, "request_id": d.request_id}
    # segundo cancel → não está mais WAITING
    with pytest.raises(AllocatorStoreError, match="WAITING"):
        await store.cancel_queued_request(d.request_id)


async def test_cancel_unknown_request_raises(store_a):
    with pytest.raises(AllocatorStoreError, match="não existe"):
        await store_a.cancel_queued_request("req-nope")


async def test_release_drains_queue(make_store):
    # cap cabe exatamente 1 VM cpu-small (0.10); o segundo request vai p/ fila; ao liberar
    # o primeiro, a fila é drenada e provisiona o segundo.
    store = await make_store(TENANT_A, AllocatorPolicy(max_cost_usd_per_hour=0.10))
    d1 = await store.request_vm(_req(owner="a", exclusive=True))
    assert d1.outcome == "LEASED"
    d2 = await store.request_vm(_req(owner="b", exclusive=True))
    assert d2.outcome == "QUEUED"

    await store.release_lease(d1.lease.lease_id)
    # o request enfileirado foi FULFILLED → agora existe um lease ativo para owner b
    leases_b = await store.list_leases(owner="b", status="ACTIVE")
    assert len(leases_b) == 1


# ── Preempção (alta prioridade) ───────────────────────────────────────────────
async def test_high_priority_preempts_low(make_store):
    store = await make_store(TENANT_A, AllocatorPolicy(max_cost_usd_per_hour=0.10))
    low = await store.request_vm(_req(owner="low", priority="low", exclusive=True))
    assert low.outcome == "LEASED"

    high = await store.request_vm(_req(owner="high", priority="high", exclusive=True))
    assert high.outcome == "LEASED"  # preemptou a VM low-priority p/ caber
    # o lease low-priority foi preemptado (RELEASED)
    preempted = await store.get_lease(low.lease.lease_id)
    assert preempted.status == "RELEASED"


# ── get / release / extend ────────────────────────────────────────────────────
async def test_get_lease_none_when_absent(store_a):
    assert await store_a.get_lease("lease-nope") is None


async def test_release_is_idempotent_and_terminates_vm(store_a):
    d = await store_a.request_vm(_req())
    released = await store_a.release_lease(d.lease.lease_id, by="ops")
    assert released.status == "RELEASED"
    # segundo release → no-op idempotente
    again = await store_a.release_lease(d.lease.lease_id)
    assert again.status == "RELEASED"
    # VM ficou sem leases → chave SSH apagada (soft-delete)
    assert (await store_a._vm_keys.find(where={"vm_id": d.lease.vm_id})).rows() == []


async def test_release_unknown_raises(store_a):
    with pytest.raises(LeaseNotFound):
        await store_a.release_lease("lease-nope")


async def test_extend_lease_caps(make_store):
    store = await make_store(
        TENANT_A, AllocatorPolicy(max_extensions_per_lease=1, max_lease_duration_min=24 * 60)
    )
    d = await store.request_vm(_req(duration_min=60))
    ext = await store.extend_lease(d.lease.lease_id, 30)
    assert ext.extension_count == 1
    with pytest.raises(AllocatorStoreError, match="max_extensions"):
        await store.extend_lease(d.lease.lease_id, 30)


async def test_extend_rejects_nonpositive(store_a):
    d = await store_a.request_vm(_req())
    with pytest.raises(AllocatorStoreError, match="> 0"):
        await store_a.extend_lease(d.lease.lease_id, 0)


# ── list / pool / capacity ────────────────────────────────────────────────────
async def test_list_leases_filters(store_a):
    a = await store_a.request_vm(_req(owner="a"))
    await store_a.request_vm(_req(owner="b"))
    await store_a.release_lease(a.lease.lease_id)

    assert {lx.owner for lx in await store_a.list_leases(owner="a")} == {"a"}
    assert {lx.owner for lx in await store_a.list_leases(status="ACTIVE")} == {"b"}
    assert len(await store_a.list_leases()) == 2


async def test_list_pool_snapshot(store_a):
    await store_a.request_vm(_req(owner="a"))
    pool = await store_a.list_pool()
    assert len(pool.vms) == 1
    assert pool.active_lease_count == 1
    assert pool.total_provisioned_cost_usd_per_hour == pytest.approx(0.10)


async def test_query_capacity(store_a):
    ok = await store_a.query_capacity("cpu-small")
    assert ok.can_satisfy_now and ok.would_provision
    approval = await store_a.query_capacity("gpu-a100")
    assert not approval.can_satisfy_now
    assert approval.blocked_by == "approval_required"


# ── SSH key ───────────────────────────────────────────────────────────────────
async def test_get_lease_ssh_key_roundtrip(store_a):
    d = await store_a.request_vm(_req(owner="agent-a"))
    pem = await store_a.get_lease_ssh_key(d.lease.lease_id, owner="agent-a")
    assert pem.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")


async def test_get_lease_ssh_key_wrong_owner(store_a):
    d = await store_a.request_vm(_req(owner="agent-a"))
    with pytest.raises(AllocatorStoreError, match="owner"):
        await store_a.get_lease_ssh_key(d.lease.lease_id, owner="agent-b")


async def test_shared_vm_same_key(store_a):
    d1 = await store_a.request_vm(_req(owner="a"))
    d2 = await store_a.request_vm(_req(owner="b"))
    assert d1.lease.vm_id == d2.lease.vm_id
    pem1 = await store_a.get_lease_ssh_key(d1.lease.lease_id, owner="a")
    pem2 = await store_a.get_lease_ssh_key(d2.lease.lease_id, owner="b")
    assert pem1 == pem2


# ── GC de leases expirados ────────────────────────────────────────────────────
async def test_gc_expires_lease_and_terminates_orphan_vm(store_a):
    d = await store_a.request_vm(_req())
    vm_id = d.lease.vm_id
    # empurra o expires_at para o passado (via ORM), depois dispara GC com um get_lease
    past = _dt_to_str(now_utc() - timedelta(hours=2))
    await store_a._leases.update_where({"lease_id": d.lease.lease_id}, {"expires_at": past}, user_id=0)
    gone = await store_a.get_lease(d.lease.lease_id)
    assert gone.status == "EXPIRED"
    # VM órfã terminada + chave apagada
    assert (await store_a._vm_keys.find(where={"vm_id": vm_id})).rows() == []


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(make_store):
    store_a = await make_store(TENANT_A)
    store_b = await make_store(TENANT_B)
    await store_a.request_vm(_req(owner="only-in-a"))
    assert len(await store_a.list_leases()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_leases() == []
    assert (await store_b.list_pool()).active_lease_count == 0
