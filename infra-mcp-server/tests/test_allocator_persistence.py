"""Testes de persistência SQLite do AllocatorStore (Phase 2b).

Simulam restart do servidor abrindo uma segunda instância do store no
mesmo arquivo SQLite e verificando que leases e VMs sobrevivem.
"""

from __future__ import annotations

import pytest

from src.knowledge.allocator_store import AllocatorPolicy, AllocatorStore
from src.models.allocator import VMRequest


def _req(
    spec: str = "cpu-small",
    duration_min: int = 60,
    owner: str = "agent-x",
    exclusive: bool = False,
) -> VMRequest:
    return VMRequest(spec=spec, duration_min=duration_min, owner=owner, exclusive=exclusive)


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #
@pytest.fixture
def db_file(tmp_path):
    """Arquivo SQLite temporário; deletado pelo pytest após o teste."""
    return str(tmp_path / "test-allocator.db")


def _make_store(db_file: str, max_cost: float = 20.0) -> AllocatorStore:
    return AllocatorStore(
        db_path=db_file,
        policy=AllocatorPolicy(max_cost_usd_per_hour=max_cost),
    )


# --------------------------------------------------------------------- #
# Testes de persistência (restart simulation)                           #
# --------------------------------------------------------------------- #
def test_lease_survives_restart(db_file):
    """Lease criado antes de restart aparece na segunda instância."""
    s1 = _make_store(db_file)
    d = s1.request_vm(_req(owner="alpha"))
    assert d.outcome == "LEASED"
    lease_id = d.lease.lease_id
    vm_id = d.lease.vm_id
    s1.close()

    # "Restart" — nova instância no mesmo arquivo
    s2 = _make_store(db_file)
    found = s2.get_lease(lease_id)
    assert found is not None
    assert found.lease_id == lease_id
    assert found.vm_id == vm_id
    assert found.status == "ACTIVE"
    assert found.owner == "alpha"
    s2.close()


def test_pool_survives_restart(db_file):
    """VM no pool persiste após restart."""
    s1 = _make_store(db_file)
    s1.request_vm(_req(owner="a", exclusive=True))
    s1.request_vm(_req(spec="cpu-medium", owner="b", exclusive=True))
    pool1 = s1.list_pool()
    assert len(pool1.vms) == 2
    s1.close()

    s2 = _make_store(db_file)
    pool2 = s2.list_pool()
    assert len(pool2.vms) == 2
    specs = {vm.spec for vm in pool2.vms}
    assert specs == {"cpu-small", "cpu-medium"}
    s2.close()


def test_release_persists_after_restart(db_file):
    """Release executado antes de restart é visto como RELEASED na segunda instância."""
    s1 = _make_store(db_file)
    d = s1.request_vm(_req(owner="beta"))
    lease_id = d.lease.lease_id
    s1.release_lease(lease_id, by="test")
    s1.close()

    s2 = _make_store(db_file)
    lease = s2.get_lease(lease_id)
    assert lease is not None
    assert lease.status == "RELEASED"
    # VM terminada (sem leases) não aparece no pool
    pool = s2.list_pool()
    assert len(pool.vms) == 0
    s2.close()


def test_extension_count_persists(db_file):
    """extension_count após extend_lease sobrevive ao restart."""
    s1 = _make_store(db_file)
    d = s1.request_vm(_req(owner="gamma", duration_min=60))
    lease_id = d.lease.lease_id
    s1.extend_lease(lease_id, additional_min=30)
    s1.extend_lease(lease_id, additional_min=30)
    s1.close()

    s2 = _make_store(db_file)
    lease = s2.get_lease(lease_id)
    assert lease is not None
    assert lease.extension_count == 2
    s2.close()


def test_multiple_leases_per_owner_survive_restart(db_file):
    """list_my_leases funciona corretamente após restart."""
    s1 = _make_store(db_file)
    s1.request_vm(_req(owner="delta"))
    s1.request_vm(_req(spec="cpu-medium", owner="delta"))
    s1.close()

    s2 = _make_store(db_file)
    out = s2.list_leases(owner="delta")
    assert len(out) == 2
    assert all(lease.owner == "delta" for lease in out)
    s2.close()


def test_exclusive_lock_persists(db_file):
    """VM com exclusive lock tem exclusive_locked_by preenchido após restart."""
    s1 = _make_store(db_file)
    d = s1.request_vm(_req(owner="eps", exclusive=True))
    lease_id = d.lease.lease_id
    vm_id = d.lease.vm_id
    s1.close()

    s2 = _make_store(db_file)
    pool = s2.list_pool()
    assert len(pool.vms) == 1
    vm = pool.vms[0]
    assert vm.vm_id == vm_id
    assert vm.exclusive_locked_by == lease_id
    s2.close()


def test_sharing_works_after_restart(db_file):
    """VM compartilhável antes de restart aceita novo tenant após restart."""
    s1 = _make_store(db_file)
    d1 = s1.request_vm(_req(owner="a"))
    vm_id = d1.lease.vm_id
    s1.close()

    # Nova instância no mesmo DB: VM ainda existe e tem slot livre → compartilha
    s2 = _make_store(db_file)
    d2 = s2.request_vm(_req(owner="b"))
    assert d2.outcome == "LEASED"
    assert d2.lease.vm_id == vm_id  # mesmo VM
    s2.close()


def test_cost_cap_enforced_across_restart(db_file):
    """Cost cap respeita VMs já provisionadas antes de restart."""
    # Cost cap apertado: só cabe 1 cpu-small ($0.10/h de $0.15/h total)
    s1 = _make_store(db_file, max_cost=0.15)
    d1 = s1.request_vm(_req(owner="a", exclusive=True))
    assert d1.outcome == "LEASED"
    s1.close()

    # Segunda instância: pool tem 1 VM ($0.10/h), tentar + $0.10/h viola cap
    s2 = _make_store(db_file, max_cost=0.15)
    d2 = s2.request_vm(_req(owner="b", exclusive=True))
    assert d2.outcome == "QUEUED"
    s2.close()


def test_schema_is_idempotent(db_file):
    """Abrir a mesma store duas vezes sem fechar não corrompe schema."""
    s1 = _make_store(db_file)
    s1.request_vm(_req(owner="x"))
    # Segunda instância no mesmo arquivo enquanto s1 ainda está aberta
    s2 = _make_store(db_file)
    pool = s2.list_pool()
    assert len(pool.vms) >= 1
    s1.close()
    s2.close()


def test_memory_store_isolation():
    """:memory: stores são sempre isoladas — sem interferência entre instâncias."""
    s1 = AllocatorStore()  # :memory:
    s2 = AllocatorStore()  # outro :memory:
    s1.request_vm(_req(owner="a"))
    # s2 não vê dados de s1
    pool = s2.list_pool()
    assert len(pool.vms) == 0
    s1.close()
    s2.close()
