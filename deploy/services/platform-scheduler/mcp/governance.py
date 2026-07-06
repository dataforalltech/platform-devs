"""Per-service Twin PEP for the platform-scheduler MCP sidecar (DTR standard).

Every platform MCP enforces its OWN inner Twin Token (``aud mcp:scheduler``) + the PDP
(G1 identity/revocation, G2 mandate, G3 scope) on each tools/call BEFORE dispatch, via the
reusable ``platform_governance.policy.service_pep.TwinPep`` enabler (defense in depth,
INV-1). Health tools are exempt. Verb is detected on the namespace-stripped name so a
prefixed tool can never mask a write and let a read scope authorize it (INV-2).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

NAMESPACE = "scheduler"
AUDIENCE = "mcp:scheduler"

EXEMPT_TOOLS: frozenset[str] = frozenset({"check_health", "check_readiness", "health_check", "ping"})

_WRITE_PREFIXES: tuple[str, ...] = (
    "create_", "update_", "delete_", "add_", "remove_", "set_", "put_", "patch_", "post_",
    "provision_", "revoke_", "grant_", "approve_", "deny_", "publish_", "retire_", "enable_",
    "disable_", "rotate_", "reset_", "assign_", "unassign_", "convert_", "sync_", "merge_",
    "link_", "unlink_", "import_", "archive_", "restore_", "bulk_", "send_", "move_", "close_",
    "run_", "trigger_", "start_", "stop_", "execute_", "pause_", "resume_", "schedule_",
    "unschedule_", "cancel_", "retry_", "migrate_",
)


# #22: prefer the shared lib's comprehensive WRITE_PREFIXES (single source of truth) when the
# installed platform_governance provides it; the local tuple above is the fallback for older libs.
try:
    from platform_governance.policy import WRITE_PREFIXES as _WRITE_PREFIXES  # type: ignore  # noqa: F811
except Exception:  # noqa: BLE001
    pass


def capability_for(tool_name: str) -> tuple[str, str, str]:
    """Return ``(capability, required_scope, resource_type)``. required_scope is
    namespace-level (``*:scheduler:<verb>``) to match the gateway PEP."""
    bare = tool_name
    if bare.startswith(f"{NAMESPACE}_"):
        bare = bare[len(NAMESPACE) + 1 :]
    verb = "write" if bare.lower().startswith(_WRITE_PREFIXES) else "read"
    resource = bare
    for p in _WRITE_PREFIXES:
        if resource.lower().startswith(p):
            resource = resource[len(p) :]
            break
    resource = (resource.split("_", 1)[0] or "unknown").lower()
    return f"{NAMESPACE}.{resource}.{verb}", f"*:{NAMESPACE}:{verb}", NAMESPACE


@lru_cache(maxsize=1)
def get_twin_pep() -> Any | None:
    if os.environ.get("SCHEDULER_MCP_TWIN_ENFORCE", "").lower() not in ("1", "true", "yes"):
        return None
    jwks = os.environ.get("SCHEDULER_MCP_TWIN_JWKS_URL") or os.environ.get("URL_ADMIN_TWIN_JWKS")
    if not jwks:
        raise RuntimeError("SCHEDULER_MCP_TWIN_ENFORCE set but no JWKS URL (URL_ADMIN_TWIN_JWKS).")
    from platform_governance.policy.service_pep import TwinPep

    return TwinPep(jwks_url=jwks, audience=AUDIENCE)


async def enforce_tool(request: Any, tool_name: str, arguments: dict | None):
    pep = get_twin_pep()
    bare = tool_name[len(NAMESPACE) + 1 :] if tool_name.startswith(f"{NAMESPACE}_") else tool_name
    if pep is None or tool_name in EXEMPT_TOOLS or bare in EXEMPT_TOOLS:
        return None
    capability, required_scope, resource_type = capability_for(tool_name)
    return await pep.enforce(
        request, capability=capability, arguments=arguments or {},
        resource_type=resource_type, required_scope=required_scope,
    )
