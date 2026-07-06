"""Servidor MCP do platform-iceberg — expõe operações de tenant/warehouse/user/permissions.

Rodar standalone:
  python -m iceberg_mcp.server

Ou via sidecar HTTP (porta 7104 por padrão):
  MCP_HTTP_PORT=7104 python -m iceberg_mcp.server
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

# --------------------------------------------------------------------------- #
# Config                                                                       #
# --------------------------------------------------------------------------- #
_ICEBERG_BASE_URL = os.environ.get("ICEBERG_INTERNAL_URL", "http://localhost:8018/api/v1")
_ICEBERG_INTERNAL_TOKEN = os.environ.get("ICEBERG_INTERNAL_TOKEN", "")
_ICEBERG_HEALTH_URL = os.environ.get("ICEBERG_HEALTH_URL", "http://localhost:8018/api/health/ready")
_MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "7104"))


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if _ICEBERG_INTERNAL_TOKEN:
        h["Authorization"] = f"Bearer {_ICEBERG_INTERNAL_TOKEN}"
    return h


def _require_tenant_id(tenant_id: str) -> None:
    """Garante que tenant_id seja fornecido e não seja o valor padrão proibido."""
    if not tenant_id or tenant_id == "default":
        raise ValueError("tenant_id obrigatório e não pode ser 'default'")


# --------------------------------------------------------------------------- #
# FastMCP bootstrap                                                            #
# --------------------------------------------------------------------------- #
from .auth import build_token_verifier  # noqa: E402

_token_verifier = build_token_verifier()

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except ImportError:
    from fastmcp import FastMCP  # type: ignore

try:
    mcp = FastMCP("platform-iceberg MCP", token_verifier=_token_verifier)
except (TypeError, ValueError):
    mcp = FastMCP("platform-iceberg MCP")


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _get(path: str) -> dict[str, Any]:
    import httpx
    url = f"{_ICEBERG_BASE_URL}{path}"
    try:
        r = httpx.get(url, headers=_headers(), timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "url": url}


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    import httpx
    url = f"{_ICEBERG_BASE_URL}{path}"
    try:
        r = httpx.post(url, headers=_headers(), json=payload, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "url": url}


def _delete(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx
    url = f"{_ICEBERG_BASE_URL}{path}"
    try:
        r = httpx.delete(url, headers=_headers(), json=payload, timeout=15)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status": "deleted"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "url": url}


# --------------------------------------------------------------------------- #
# Tools — Tenants                                                              #
# --------------------------------------------------------------------------- #
@mcp.tool()
def list_iceberg_tenants(tenant_id: str = "default") -> dict:
    """Lista todos os tenants Iceberg disponíveis."""
    _require_tenant_id(tenant_id)
    return _get("/tenants")


@mcp.tool()
def get_iceberg_tenant(target_tenant_id: str, tenant_id: str = "default") -> dict:
    """Retorna detalhes de um tenant Iceberg específico."""
    _require_tenant_id(tenant_id)
    return _get(f"/tenants/{target_tenant_id}")


@mcp.tool()
def create_iceberg_tenant(
    new_tenant_id: str,
    description: str | None = None,
    tenant_id: str = "default",
) -> dict:
    """Cria um novo tenant Iceberg."""
    _require_tenant_id(tenant_id)
    payload: dict[str, Any] = {"tenant_id": new_tenant_id}
    if description is not None:
        payload["description"] = description
    return _post("/tenants", payload)


@mcp.tool()
def delete_iceberg_tenant(target_tenant_id: str, tenant_id: str = "default") -> dict:
    """Remove um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    return _delete(f"/tenants/{target_tenant_id}")


@mcp.tool()
def rotate_iceberg_tenant_token(target_tenant_id: str, tenant_id: str = "default") -> dict:
    """Rotaciona o token de acesso de um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    return _post(f"/tenants/{target_tenant_id}/rotate-token", {})


# --------------------------------------------------------------------------- #
# Tools — Warehouses                                                           #
# --------------------------------------------------------------------------- #
@mcp.tool()
def create_iceberg_warehouse(
    target_tenant_id: str,
    name: str,
    storage_type: str,
    bucket: str,
    region: str | None = None,
    endpoint_url: str | None = None,
    default_schema: str = "default",
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    tenant_id: str = "default",
) -> dict:
    """Cria um warehouse Iceberg. storage_type: 's3' | 'gcs' | 'adls'."""
    _require_tenant_id(tenant_id)
    storage: dict[str, Any] = {"type": storage_type, "bucket": bucket}
    if region:
        storage["region"] = region
    if endpoint_url:
        storage["endpoint_url"] = endpoint_url
    if storage_type == "s3":
        if aws_access_key_id:
            storage["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            storage["aws_secret_access_key"] = aws_secret_access_key
    payload: dict[str, Any] = {
        "name": name,
        "storage": storage,
        "default_schema": default_schema,
    }
    return _post(f"/tenants/{target_tenant_id}/warehouses", payload)


@mcp.tool()
def list_iceberg_warehouses(target_tenant_id: str, tenant_id: str = "default") -> dict:
    """Lista warehouses de um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    return _get(f"/tenants/{target_tenant_id}/warehouses")


# --------------------------------------------------------------------------- #
# Tools — SQL Users                                                            #
# --------------------------------------------------------------------------- #
@mcp.tool()
def create_iceberg_sql_user(
    target_tenant_id: str,
    username: str,
    role: str = "reader",
    password: str | None = None,
    tenant_id: str = "default",
) -> dict:
    """Cria um usuário SQL para um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    payload: dict[str, Any] = {"username": username, "role": role}
    if password is not None:
        payload["password"] = password
    return _post(f"/tenants/{target_tenant_id}/users", payload)


@mcp.tool()
def list_iceberg_sql_users(target_tenant_id: str, tenant_id: str = "default") -> dict:
    """Lista usuários SQL de um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    return _get(f"/tenants/{target_tenant_id}/users")


# --------------------------------------------------------------------------- #
# Tools — Permissions                                                          #
# --------------------------------------------------------------------------- #
@mcp.tool()
def grant_iceberg_permission(
    target_tenant_id: str,
    username: str,
    privilege: str = "SELECT",
    schema_name: str | None = None,
    tenant_id: str = "default",
) -> dict:
    """Concede uma permissão a um usuário em um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    payload: dict[str, Any] = {"username": username, "privilege": privilege}
    if schema_name is not None:
        payload["schema_name"] = schema_name
    return _post(f"/tenants/{target_tenant_id}/permissions", payload)


@mcp.tool()
def revoke_iceberg_permission(
    target_tenant_id: str,
    username: str,
    privilege: str = "SELECT",
    schema_name: str | None = None,
    tenant_id: str = "default",
) -> dict:
    """Revoga uma permissão de um usuário em um tenant Iceberg."""
    _require_tenant_id(tenant_id)
    payload: dict[str, Any] = {"username": username, "privilege": privilege}
    if schema_name is not None:
        payload["schema_name"] = schema_name
    return _delete(f"/tenants/{target_tenant_id}/permissions", payload)


@mcp.tool()
def list_iceberg_permissions(
    target_tenant_id: str,
    username: str | None = None,
    tenant_id: str = "default",
) -> dict:
    """Lista permissões de um tenant Iceberg, opcionalmente filtrado por usuário."""
    _require_tenant_id(tenant_id)
    path = f"/tenants/{target_tenant_id}/permissions"
    if username:
        path += f"?username={username}"
    return _get(path)


# --------------------------------------------------------------------------- #
# Tools — Health                                                               #
# --------------------------------------------------------------------------- #
@mcp.tool()
def health_check(tenant_id: str = "default") -> dict:
    """Verifica a saúde do platform-iceberg."""
    _require_tenant_id(tenant_id)
    import httpx
    try:
        r = httpx.get(_ICEBERG_HEALTH_URL, headers=_headers(), timeout=5)
        if r.status_code < 300:
            return {"status": "ok", "service": "platform-iceberg"}
        return {"status": "degraded", "service": "platform-iceberg", "http_status": r.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "service": "platform-iceberg", "error": str(exc)}


# --------------------------------------------------------------------------- #
# Entrypoint                                                                   #
# --------------------------------------------------------------------------- #
def main() -> None:
    from iceberg_mcp.http_sidecar import MCPHttpSidecar

    sidecar = MCPHttpSidecar(mcp, port=_MCP_HTTP_PORT)
    asyncio.run(sidecar.serve())


if __name__ == "__main__":
    main()
