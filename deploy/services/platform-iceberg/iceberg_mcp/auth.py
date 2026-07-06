"""HMAC-based token verifier for the platform-iceberg MCP sidecar."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

NAMESPACE = "iceberg"
AUDIENCE = "mcp:iceberg"

_PROFILE_SCOPES: dict[str, list[str]] = {
    "iceberg-admin": ["*"],
    "iceberg-operator": [
        "tenants:write",
        "warehouses:write",
        "users:write",
        "permissions:write",
    ],
    "iceberg-viewer": [
        "tenants:read",
        "warehouses:read",
        "users:read",
        "permissions:read",
    ],
    "iceberg-pipeline": ["warehouses:read", "permissions:read"],
}


def _validate_auth_config(secret: str | None) -> None:
    env = os.environ.get("ENVIRONMENT", "dev").lower()
    if env in {"prod", "production", "staging"} and not secret:
        raise RuntimeError(
            "MCP_SERVICE_TOKEN must be set in production/staging environments. "
            "Platform-iceberg MCP will not start without it."
        )


class MCPServiceTokenVerifier:
    """Verifies HMAC tokens in format `{profile_id}:{tenant_id}:{hmac_hex}`."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def verify(self, token: str) -> dict[str, Any] | None:
        parts = token.split(":", 2)
        if len(parts) != 3:
            return None
        profile_id, tenant_id, provided_hmac = parts
        expected = hmac.new(
            self._secret,
            f"{profile_id}:{tenant_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided_hmac, expected):
            return None
        scopes = _PROFILE_SCOPES.get(profile_id)
        if scopes is None:
            return None
        return {
            "profile_id": profile_id,
            "tenant_id": tenant_id,
            "scopes": scopes,
            "audience": AUDIENCE,
        }


def build_token_verifier() -> MCPServiceTokenVerifier | None:
    secret = os.environ.get("MCP_SERVICE_TOKEN", "")
    _validate_auth_config(secret or None)
    if not secret:
        return None
    return MCPServiceTokenVerifier(secret)


def generate_mcp_token(profile_id: str, tenant_id: str, secret: str) -> str:
    mac = hmac.new(
        secret.encode(),
        f"{profile_id}:{tenant_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{profile_id}:{tenant_id}:{mac}"


def parse_mcp_context(claims: dict[str, Any]) -> tuple[str, list[str]]:
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise ValueError("JWT sem tenant_id claim — acesso negado (fail-closed)")
    scopes = claims.get("scopes", [])
    return tenant_id, scopes
