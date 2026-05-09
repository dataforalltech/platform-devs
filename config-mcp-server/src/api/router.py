"""HTTP API interna do config-mcp — consumida por outros MCP servers.

Endpoints:
  GET  /v1/health                          → {"status": "ok"}
  GET  /v1/credentials/{namespace}/{key}   → {"value": "..."}
  GET  /v1/credentials/{namespace}         → {"keys": [...], "namespace": "..."}
  GET  /v1/namespaces                      → {"namespaces": [...]}
  GET  /v1/env/{environment}               → {"DATABASE_URL": "...", ...}
  GET  /v1/tenants                         → {"tenants": [...]}
  GET  /v1/tenants/{tenant_id}             → {"KEY": "...", ...}
  GET  /v1/physical                        → {os, cpu, ram, disks, network}

Auth: Bearer token no header Authorization (opcional se api_token vazio).
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..knowledge.store import ConfigStore
from ..knowledge.sysinfo import collect_physical_info

_log = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def make_router(store: ConfigStore, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/v1")

    # ── Auth ──────────────────────────────────────────────────────────────── #
    def _check_auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
        if not api_token:
            return  # auth desabilitada
        if not creds or not secrets.compare_digest(creds.credentials, api_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")

    auth = Depends(_check_auth)

    # ── Endpoints ─────────────────────────────────────────────────────────── #

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "config-mcp"}

    @router.get("/namespaces", dependencies=[auth])
    async def list_namespaces() -> dict[str, Any]:
        return {"namespaces": store.list_namespaces()}

    @router.get("/credentials/{namespace}/{key}", dependencies=[auth])
    async def get_credential(namespace: str, key: str) -> dict[str, Any]:
        value = store.get(namespace, key)
        if value is None:
            raise HTTPException(status_code=404, detail=f"{namespace}.{key} não encontrado.")
        return {"namespace": namespace, "key": key, "value": value}

    @router.get("/credentials/{namespace}", dependencies=[auth])
    async def list_namespace_keys(namespace: str) -> dict[str, Any]:
        return {"namespace": namespace, "keys": store.list_keys(namespace).get(namespace, [])}

    @router.get("/env/{environment}", dependencies=[auth])
    async def get_env_config(environment: str) -> dict[str, Any]:
        ns = f"env.{environment}"
        return store.get_namespace(ns)

    @router.get("/tenants", dependencies=[auth])
    async def list_tenants() -> dict[str, Any]:
        tenants = [
            ns.removeprefix("tenants.")
            for ns in store.list_namespaces()
            if ns.startswith("tenants.")
        ]
        return {"tenants": sorted(tenants)}

    @router.get("/tenants/{tenant_id}", dependencies=[auth])
    async def get_tenant_config(tenant_id: str) -> dict[str, Any]:
        ns = f"tenants.{tenant_id}"
        config = store.get_namespace(ns)
        if not config:
            raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' não encontrado.")
        return config

    @router.get("/physical", dependencies=[auth])
    async def get_physical() -> dict[str, Any]:
        return collect_physical_info()

    return router
