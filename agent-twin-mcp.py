#!/usr/bin/env python3
"""Agent-Twin MCP - simplified Claude Code compatible version."""
import json
import sys
import os
from datetime import datetime, timezone

# Simple in-memory token store (replace with real DB for production)
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

class SimplifiedTokenStore:
    """Minimal token store for demo."""

    def validate(self, token: str) -> dict:
        """Validate token and return user record."""
        return _TOKENS.get(token)

    def touch(self, user_id: str) -> None:
        """Update last access time."""
        pass

class SimplifiedSessionManager:
    """Minimal session manager for demo."""

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

def authenticate(store, token: str) -> dict:
    """Authenticate user and initialize session."""
    record = store.validate(token)
    if not record:
        return {
            "authenticated": False,
            "error": "Token inválido, expirado ou revogado.",
        }

    session = {
        "token": token,
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
    SimplifiedSessionManager.set(session)
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

def whoami() -> dict:
    """Return authenticated user info."""
    session = SimplifiedSessionManager.get()
    if not session:
        return {
            "authenticated": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }
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

def get_twin_context() -> dict:
    """Return complete session context: user + environment."""
    session = SimplifiedSessionManager.get()
    if not session:
        return {
            "authenticated": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }

    # Collect minimal environment context
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

def context_status() -> dict:
    """Return context metrics and recommendation."""
    session = SimplifiedSessionManager.get()
    if not session:
        return {
            "authenticated": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }

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

def refresh_context() -> dict:
    """Force re-collect environment context."""
    session = SimplifiedSessionManager.get()
    if not session:
        return {
            "success": False,
            "error": "Nenhuma sessão ativa. Chame authenticate(token) primeiro.",
        }

    new_context = {
        "cwd": os.getcwd(),
        "python_version": sys.version.split()[0],
        "user": os.getenv("USER", "unknown"),
        "hostname": os.getenv("HOSTNAME", "unknown"),
    }
    SimplifiedSessionManager.update_context(new_context)

    return {
        "success": True,
        "user_id": session["user_id"],
        "context": new_context,
    }

def main():
    """Run MCP server."""
    store = SimplifiedTokenStore()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            msg = json.loads(line)
            msg_id = msg.get("id", 0)
            method = msg.get("method", "")
            params = msg.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "agent-twin-mcp",
                            "version": "1.0"
                        }
                    }
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [
                            {
                                "name": "authenticate",
                                "description": "Validate token and initialize session",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "token": {"type": "string", "description": "User token"}
                                    },
                                    "required": ["token"]
                                }
                            },
                            {
                                "name": "whoami",
                                "description": "Get current authenticated user",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "get_twin_context",
                                "description": "Get complete session context (user + environment)",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "context_status",
                                "description": "Get context metrics and recommendation",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "refresh_context",
                                "description": "Force re-collect environment context",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                        ]
                    }
                }
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})

                try:
                    if tool_name == "authenticate":
                        result = authenticate(store, token=tool_args.get("token", ""))
                    elif tool_name == "whoami":
                        result = whoami()
                    elif tool_name == "get_twin_context":
                        result = get_twin_context()
                    elif tool_name == "context_status":
                        result = context_status()
                    elif tool_name == "refresh_context":
                        result = refresh_context()
                    else:
                        result = {"error": f"unknown tool: {tool_name}"}
                except Exception as e:
                    result = {"error": str(e)}

                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"ok": True}
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError:
            pass
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()

if __name__ == "__main__":
    main()
