#!/usr/bin/env python3
"""Agent-Twin MCP - HTTP wrapper para versão JSON-RPC."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import os
import sys

app = FastAPI(
    title="Agent-Twin MCP",
    description="Authentication and context management for Claude Code",
    version="1.0"
)

# Simples token store (replace with real DB para produção)
_TOKENS = {
    "demo-token-001": {
        "user_id": "user_001",
        "name": "Demo User",
        "email": "demo@example.com",
        "role": "developer",
        "scopes": ["read:context", "write:artifacts"],
        "environment": "development",
        "tenant_id": "tenant_dev",
    }
}

_SESSIONS = {}

class TokenStore:
    """Token store manager."""
    def validate(self, token: str) -> dict:
        """Validate token and return user record."""
        return _TOKENS.get(token)

    def touch(self, user_id: str) -> None:
        """Update last access time."""
        pass

class SessionManager:
    """Session manager."""
    _session = None

    @classmethod
    def set(cls, session):
        cls._session = session

    @classmethod
    def get(cls):
        return cls._session

    @classmethod
    def update_context(cls, context):
        if cls._session:
            cls._session["context"] = context

# Initialize
store = TokenStore()

# Models
class AuthenticateRequest(BaseModel):
    token: str

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}

@app.post("/authenticate")
async def authenticate(req: AuthenticateRequest):
    """Authenticate user and initialize session."""
    record = store.validate(req.token)
    if not record:
        raise HTTPException(
            status_code=401,
            detail="Token inválido, expirado ou revogado."
        )

    session = {
        "token": req.token,
        "user_id": record["user_id"],
        "name": record["name"],
        "email": record["email"],
        "role": record["role"],
        "scopes": record["scopes"],
        "environment": record["environment"],
        "tenant_id": record.get("tenant_id"),
        "authenticated_at": datetime.now(timezone.utc).isoformat(),
        "context": {},
        "tool_calls": 0,
    }
    SessionManager.set(session)
    store.touch(record["user_id"])

    return {
        "authenticated": True,
        "user_id": session["user_id"],
        "name": session["name"],
        "role": session["role"],
        "environment": session["environment"],
        "tenant_id": session["tenant_id"],
        "message": f"Bem-vindo, {session['name']}! Use get_twin_context() para contexto completo.",
    }

@app.get("/whoami")
async def whoami():
    """Return authenticated user info."""
    session = SessionManager.get()
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Nenhuma sessão ativa. Chame authenticate(token) primeiro."
        )
    return {
        "authenticated": True,
        "user_id": session["user_id"],
        "name": session["name"],
        "email": session["email"],
        "role": session["role"],
        "scopes": session["scopes"],
        "environment": session["environment"],
        "tenant_id": session["tenant_id"],
        "authenticated_at": session["authenticated_at"],
    }

@app.get("/get_twin_context")
async def get_twin_context():
    """Return complete session context: user + environment."""
    session = SessionManager.get()
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Nenhuma sessão ativa. Chame authenticate(token) primeiro."
        )

    context = {
        "cwd": os.getcwd(),
        "python_version": sys.version.split()[0],
        "user": os.getenv("USER", "unknown"),
        "hostname": os.getenv("HOSTNAME", "unknown"),
    }

    tenant_namespaces = [f"tenants.{session['tenant_id']}"] if session["tenant_id"] else []
    return {
        "authenticated": True,
        "user": {
            "user_id": session["user_id"],
            "name": session["name"],
            "email": session["email"],
            "role": session["role"],
            "scopes": session["scopes"],
            "environment": session["environment"],
            "tenant_id": session["tenant_id"],
        },
        "context": context,
        "authenticated_at": session["authenticated_at"],
        "credential_namespaces": [
            f"credentials.{session['user_id']}",
            "credentials.acr",
            "credentials.github",
            f"env.{session['environment']}",
        ],
        "tenant_namespaces": tenant_namespaces,
    }

@app.get("/context_status")
async def context_status():
    """Return context metrics and recommendation."""
    session = SessionManager.get()
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Nenhuma sessão ativa. Chame authenticate(token) primeiro."
        )

    now = datetime.now(timezone.utc)
    authenticated_at = datetime.fromisoformat(session["authenticated_at"])
    elapsed_minutes = (now - authenticated_at).total_seconds() / 60
    tool_calls = session.get("tool_calls", 0)

    if tool_calls >= 150:
        recommendation = "compact_now"
        message = f"Contexto muito extenso ({tool_calls} tool calls). Execute /compact."
    elif tool_calls >= 80:
        recommendation = "compact_soon"
        message = f"Contexto crescendo ({tool_calls} tool calls). Considere /compact."
    else:
        recommendation = "ok"
        message = f"Contexto saudável ({tool_calls} tool calls)."

    return {
        "authenticated": True,
        "user_id": session["user_id"],
        "tool_calls": tool_calls,
        "elapsed_minutes": round(elapsed_minutes, 1),
        "authenticated_at": session["authenticated_at"],
        "recommendation": recommendation,
        "message": message,
    }

@app.post("/refresh_context")
async def refresh_context():
    """Force re-collect environment context."""
    session = SessionManager.get()
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Nenhuma sessão ativa. Chame authenticate(token) primeiro."
        )

    new_context = {
        "cwd": os.getcwd(),
        "python_version": sys.version.split()[0],
        "user": os.getenv("USER", "unknown"),
        "hostname": os.getenv("HOSTNAME", "unknown"),
    }
    SessionManager.update_context(new_context)

    return {
        "success": True,
        "user_id": session["user_id"],
        "context": new_context,
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 7101))
    uvicorn.run(app, host="0.0.0.0", port=port)
