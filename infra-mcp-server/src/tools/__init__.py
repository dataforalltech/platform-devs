"""Tools MCP do infra-mcp-server.

Phase 1 — read-only wrappers sobre CLIs externas (terraform, checkov, infracost).
Phase 2a — VM allocator in-memory (request_vm, get/release/extend_lease,
list_my_leases, list_pool, query_capacity).
Phase 2f — SSH key per-VM (get_lease_ssh_key).
Phase 2h — priority queue + preemption (cancel_queued_request).
"""

from .allocator_tool import (
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
from .checkov_tool import policy_scan_checkov
from .infracost_tool import cost_estimate_infracost
from .terraform_tool import (
    terraform_fmt_check,
    terraform_plan,
    terraform_show_plan,
    terraform_validate,
)

__all__ = [
    # Phase 1
    "terraform_validate",
    "terraform_fmt_check",
    "terraform_plan",
    "terraform_show_plan",
    "policy_scan_checkov",
    "cost_estimate_infracost",
    # Phase 2a — allocator
    "request_vm",
    "get_lease",
    "release_lease",
    "extend_lease",
    "list_my_leases",
    "list_pool",
    "query_capacity",
    # Phase 2f — SSH key
    "get_lease_ssh_key",
    # Phase 2h — priority queue
    "cancel_queued_request",
]
