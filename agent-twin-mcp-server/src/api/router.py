"""HTTP API :7098 — consultada por outros MCPs para saber quem está operando.

Endpoints:
  GET /v1/health                → {"status": "ok", "service": "agent-twin-mcp"}
  GET /v1/session               → sessão autenticada atual (sem token)
  GET /v1/session/user          → dados do usuário (inclui tenant_id)
  GET /v1/session/tenant        → tenant_id da sessão atual (para config-mcp)
  GET /v1/session/context       → contexto de ambiente
  POST /v1/session/check-scope  → {"scope": "deploy"} → 200 allowed / 403 denied

Segurança:
  - Bearer comparison usa secrets.compare_digest (timing-safe).
  - /v1/health não expõe estado de autenticação (evitar info leak).
  - /v1/session/scopes removido (redundante com /v1/session/user).
  - check-scope retorna 403 quando escopo negado (não 200 com allowed: false).
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ..knowledge.session import SessionManager

_bearer = HTTPBearer(auto_error=False)


class ScopeCheckRequest(BaseModel):
    scope: str


def make_router(api_token: str) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def _check_auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
        if not api_token:
            return
        if not creds or not secrets.compare_digest(creds.credentials, api_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")

    auth = Depends(_check_auth)

    @router.get("/health")
    async def health() -> dict[str, str]:
        # Não expõe estado de autenticação (evitar info leak a endpoints não autenticados)
        return {"status": "ok", "service": "agent-twin-mcp"}

    @router.get("/session", dependencies=[auth])
    async def get_session() -> dict[str, Any]:
        session = SessionManager.get()
        if not session:
            raise HTTPException(status_code=404, detail="Nenhuma sessão autenticada.")
        return {
            "user_id": session.user_id,
            "name": session.name,
            "email": session.email,
            "role": session.role,
            "scopes": session.scopes,
            "environment": session.environment,
            "tenant_id": session.tenant_id,
            "authenticated_at": session.authenticated_at,
            "context": session.context,
        }

    @router.get("/session/user", dependencies=[auth])
    async def get_user() -> dict[str, Any]:
        session = SessionManager.get()
        if not session:
            raise HTTPException(status_code=404, detail="Nenhuma sessão autenticada.")
        return {
            "user_id": session.user_id,
            "name": session.name,
            "email": session.email,
            "role": session.role,
            "scopes": session.scopes,
            "environment": session.environment,
            "tenant_id": session.tenant_id,
        }

    @router.get("/session/tenant", dependencies=[auth])
    async def get_tenant() -> dict[str, Any]:
        """Retorna o tenant_id da sessão atual. Consumido pelo config-mcp."""
        session = SessionManager.get()
        if not session:
            raise HTTPException(status_code=404, detail="Nenhuma sessão autenticada.")
        return {
            "tenant_id": session.tenant_id,
            "user_id": session.user_id,
            "has_tenant": session.tenant_id is not None,
        }

    @router.post("/session/check-scope", dependencies=[auth])
    async def check_scope(req: ScopeCheckRequest) -> dict[str, Any]:
        session = SessionManager.get()
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nenhuma sessão autenticada.")
        allowed = "*" in session.scopes or req.scope in session.scopes
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Escopo '{req.scope}' não autorizado para role '{session.role}'.",
            )
        return {"allowed": True, "scope": req.scope, "role": session.role}

    @router.get("/session/context", dependencies=[auth])
    async def get_context() -> dict[str, Any]:
        session = SessionManager.get()
        if not session:
            raise HTTPException(status_code=404, detail="Nenhuma sessão autenticada.")
        return session.context

    return router
