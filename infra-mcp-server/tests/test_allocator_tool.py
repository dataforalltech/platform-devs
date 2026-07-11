"""Tools MCP do allocator (async) sobre o AllocatorStore tenant-scoped (MySQL real).

Cobre os wrappers de ``src/tools/allocator_tool.py``: happy paths + mapeamento de erro
(``_error``) para validation_error / lease_not_found / allocator_error."""

from __future__ import annotations

import pytest

from src.db.allocator_store import AllocatorPolicy
from src.tools.allocator_tool import (
    cancel_queued_request,
    extend_lease,
    get_lease,
    get_lease_ssh_key,
    list_my_leases,
    list_pool,
    query_capacity,
    release_lease,
    request_vm,
)

from .conftest import TENANT_A, requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


async def test_request_vm_happy_path(store_a):
    res = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    assert res["outcome"] == "LEASED"
    assert res["lease"]["status"] == "ACTIVE"


async def test_request_vm_invalid_spec(store_a):
    res = await request_vm(store_a, spec="nope", duration_min=60, owner="agent")
    assert res["error"] == "validation_error"


async def test_request_vm_empty_owner(store_a):
    res = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="")
    assert res["error"] == "validation_error"


async def test_get_lease_found_and_missing(store_a):
    d = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    lease_id = d["lease"]["lease_id"]
    found = await get_lease(store_a, lease_id=lease_id)
    assert found["found"] is True
    assert found["lease"]["lease_id"] == lease_id

    missing = await get_lease(store_a, lease_id="lease-nope")
    assert missing == {"found": False, "lease_id": "lease-nope"}


async def test_release_lease(store_a):
    d = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await release_lease(store_a, lease_id=d["lease"]["lease_id"], by="ops")
    assert res["lease"]["status"] == "RELEASED"


async def test_release_lease_not_found(store_a):
    res = await release_lease(store_a, lease_id="lease-nope")
    assert res["error"] == "lease_not_found"


async def test_extend_lease(store_a):
    d = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await extend_lease(store_a, lease_id=d["lease"]["lease_id"], additional_min=30)
    assert res["lease"]["extension_count"] == 1


async def test_extend_lease_invalid(store_a):
    d = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await extend_lease(store_a, lease_id=d["lease"]["lease_id"], additional_min=0)
    assert res["error"] == "validation_error"


async def test_list_my_leases(store_a):
    await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await list_my_leases(store_a, owner="agent")
    assert res["total"] == 1
    assert res["leases"][0]["owner"] == "agent"


async def test_list_pool(store_a):
    await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await list_pool(store_a)
    assert res["active_lease_count"] == 1
    assert len(res["vms"]) == 1


async def test_query_capacity(store_a):
    res = await query_capacity(store_a, spec="cpu-small")
    assert res["can_satisfy_now"] is True


async def test_query_capacity_invalid_spec(store_a):
    res = await query_capacity(store_a, spec="nope")
    assert res["error"] == "validation_error"


async def test_get_lease_ssh_key(store_a):
    d = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await get_lease_ssh_key(store_a, lease_id=d["lease"]["lease_id"], owner="agent")
    assert res["key_type"] == "ed25519"
    assert res["private_key_pem"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")


async def test_get_lease_ssh_key_wrong_owner(store_a):
    d = await request_vm(store_a, spec="cpu-small", duration_min=60, owner="agent")
    res = await get_lease_ssh_key(store_a, lease_id=d["lease"]["lease_id"], owner="attacker")
    assert res["error"] == "allocator_error"


async def test_cancel_queued_request(make_store):
    store = await make_store(TENANT_A, AllocatorPolicy(max_cost_usd_per_hour=0.05))
    d = await request_vm(store, spec="cpu-small", duration_min=60, owner="agent")
    assert d["outcome"] == "QUEUED"
    res = await cancel_queued_request(store, request_id=d["request_id"], by="tester")
    assert res["cancelled"] is True


async def test_cancel_queued_request_unknown(store_a):
    res = await cancel_queued_request(store_a, request_id="req-nope")
    assert res["error"] == "allocator_error"
