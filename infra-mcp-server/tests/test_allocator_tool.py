"""Testes do allocator_tool — wrappers MCP sobre o AllocatorStore."""

from __future__ import annotations

import pytest

from src.knowledge.allocator_store import AllocatorPolicy, AllocatorStore
from src.tools.allocator_tool import (
    extend_lease,
    get_lease,
    list_my_leases,
    list_pool,
    query_capacity,
    release_lease,
    request_vm,
)


@pytest.fixture
def store() -> AllocatorStore:
    return AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))


# --------------------------- request_vm --------------------------- #
def test_request_vm_happy_path(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="agent-x")
    assert res["outcome"] == "LEASED"
    assert res["lease"]["status"] == "ACTIVE"
    assert res["lease"]["spec"] == "cpu-small"


def test_request_vm_invalid_spec(store):
    res = request_vm(store, spec="quantum-cpu", duration_min=60, owner="x")
    assert res["error"] == "validation_error"
    assert "spec inválida" in res["details"]


def test_request_vm_invalid_priority(store):
    res = request_vm(
        store, spec="cpu-small", duration_min=60, owner="x", priority="urgent"
    )
    assert res["error"] == "validation_error"


def test_request_vm_empty_owner(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="")
    assert res["error"] == "validation_error"


def test_request_vm_negative_duration(store):
    res = request_vm(store, spec="cpu-small", duration_min=-5, owner="x")
    assert res["error"] == "validation_error"


def test_request_vm_gpu_denied_no_approval(store):
    res = request_vm(store, spec="gpu-a100", duration_min=60, owner="x")
    assert res["outcome"] == "DENIED"


def test_request_vm_gpu_allowed_with_approval(store):
    res = request_vm(
        store,
        spec="gpu-a100",
        duration_min=60,
        owner="x",
        human_approved=True,
    )
    assert res["outcome"] == "LEASED"


def test_request_vm_purpose_propagates(store):
    res = request_vm(
        store,
        spec="cpu-small",
        duration_min=60,
        owner="x",
        purpose="training-job-foo",
    )
    assert res["lease"]["purpose"] == "training-job-foo"


# --------------------------- get_lease --------------------------- #
def test_get_lease_returns_full_payload(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="x")
    lease_id = res["lease"]["lease_id"]
    g = get_lease(store, lease_id=lease_id)
    assert g["found"] is True
    assert g["lease"]["lease_id"] == lease_id


def test_get_lease_unknown_returns_not_found(store):
    g = get_lease(store, lease_id="lease-fake")
    assert g["found"] is False


def test_get_lease_empty_id(store):
    g = get_lease(store, lease_id="")
    assert g["error"] == "validation_error"


# --------------------------- release_lease --------------------------- #
def test_release_lease_happy_path(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="x")
    lease_id = res["lease"]["lease_id"]
    r = release_lease(store, lease_id=lease_id, by="user")
    assert r["lease"]["status"] == "RELEASED"


def test_release_lease_unknown_returns_typed_error(store):
    r = release_lease(store, lease_id="lease-bogus")
    assert r["error"] == "lease_not_found"


def test_release_lease_idempotent(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="x")
    lease_id = res["lease"]["lease_id"]
    r1 = release_lease(store, lease_id=lease_id)
    r2 = release_lease(store, lease_id=lease_id)
    assert r1["lease"]["status"] == "RELEASED"
    assert r2["lease"]["status"] == "RELEASED"


# --------------------------- extend_lease --------------------------- #
def test_extend_lease_happy_path(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="x")
    lease_id = res["lease"]["lease_id"]
    e = extend_lease(store, lease_id=lease_id, additional_min=30)
    assert e["lease"]["extension_count"] == 1


def test_extend_lease_validates_additional_min(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="x")
    lease_id = res["lease"]["lease_id"]
    e = extend_lease(store, lease_id=lease_id, additional_min=0)
    assert e["error"] == "validation_error"


def test_extend_lease_unknown(store):
    e = extend_lease(store, lease_id="lease-zz", additional_min=10)
    assert e["error"] == "lease_not_found"


# --------------------------- list_my_leases --------------------------- #
def test_list_my_leases_filters_owner(store):
    request_vm(store, spec="cpu-small", duration_min=60, owner="alpha")
    request_vm(store, spec="cpu-small", duration_min=60, owner="beta")
    out = list_my_leases(store, owner="alpha")
    assert out["total"] == 1
    assert out["leases"][0]["owner"] == "alpha"


def test_list_my_leases_filters_status(store):
    res = request_vm(store, spec="cpu-small", duration_min=60, owner="alpha")
    release_lease(store, lease_id=res["lease"]["lease_id"])
    request_vm(store, spec="cpu-small", duration_min=60, owner="alpha")
    out_active = list_my_leases(store, owner="alpha", status="ACTIVE")
    out_released = list_my_leases(store, owner="alpha", status="RELEASED")
    assert out_active["total"] == 1
    assert out_released["total"] == 1


def test_list_my_leases_empty_owner(store):
    out = list_my_leases(store, owner="")
    assert out["error"] == "validation_error"


# --------------------------- list_pool --------------------------- #
def test_list_pool_empty(store):
    out = list_pool(store)
    assert out["vms"] == []
    assert out["active_lease_count"] == 0
    assert out["total_provisioned_cost_usd_per_hour"] == 0.0


def test_list_pool_after_provisioning(store):
    request_vm(store, spec="cpu-small", duration_min=60, owner="a", exclusive=True)
    request_vm(store, spec="cpu-medium", duration_min=60, owner="b", exclusive=True)
    out = list_pool(store)
    assert len(out["vms"]) == 2
    specs = {vm["spec"] for vm in out["vms"]}
    assert specs == {"cpu-small", "cpu-medium"}


# --------------------------- query_capacity --------------------------- #
def test_query_capacity_would_provision(store):
    out = query_capacity(store, spec="cpu-small")
    assert out["can_satisfy_now"] is True
    assert out["would_provision"] is True


def test_query_capacity_invalid_spec(store):
    out = query_capacity(store, spec="not-a-spec")
    assert out["error"] == "validation_error"


def test_query_capacity_blocked_by_approval(store):
    out = query_capacity(store, spec="gpu-a100")
    assert out["can_satisfy_now"] is False
    assert out["blocked_by"] == "approval_required"


def test_query_capacity_with_owner_quota(store):
    """Owner com quota cheia → blocked_by quota."""
    s = AllocatorStore(
        policy=AllocatorPolicy(max_active_leases_per_owner=1, max_cost_usd_per_hour=100.0)
    )
    request_vm(s, spec="cpu-small", duration_min=60, owner="a", exclusive=True)
    out = query_capacity(s, spec="cpu-small", owner="a")
    assert out["blocked_by"] == "owner_concurrent_lease_cap"
