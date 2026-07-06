"""Twin PEP (policy enforcement point) for platform-iceberg MCP."""

from __future__ import annotations

import os
from typing import Any

NAMESPACE = "iceberg"
AUDIENCE = "mcp:iceberg"

EXEMPT_TOOLS: frozenset[str] = frozenset({"health_check", "ping"})

_WRITE_PREFIXES = ("create_", "delete_", "update_", "grant_", "revoke_", "rotate_")


def capability_for(tool_name: str) -> str:
    """Derive the required capability scope from a tool name."""
    name = tool_name.removeprefix(f"{NAMESPACE}_") if tool_name.startswith(NAMESPACE) else tool_name
    if any(name.startswith(p) for p in _WRITE_PREFIXES):
        action = "write"
    else:
        action = "read"
    for resource in ("tenants", "warehouses", "users", "permissions"):
        if resource.rstrip("s") in name or resource in name:
            return f"{resource}:{action}"
    return f"*:{action}"


def enforce_tool(
    tool_name: str,
    arguments: dict[str, Any],
    claims: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Enforce Twin PEP if ICEBERG_MCP_TWIN_ENFORCE=1. Returns claims or None."""
    if not os.environ.get("ICEBERG_MCP_TWIN_ENFORCE"):
        return claims
    if tool_name in EXEMPT_TOOLS:
        return claims
    if claims is None:
        raise PermissionError(f"Tool '{tool_name}' requires authentication.")
    scopes: list[str] = claims.get("scopes", [])
    if "*" in scopes:
        return claims
    required = capability_for(tool_name)
    resource, action = required.split(":")
    allowed = any(
        s == required or s == f"{resource}:*" or s == "*"
        for s in scopes
    )
    if not allowed:
        raise PermissionError(
            f"Tool '{tool_name}' requires scope '{required}'; token has {scopes}."
        )
    return claims
