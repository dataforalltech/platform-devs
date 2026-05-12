"""Bearer token validation using bcrypt and PostgreSQL."""
from __future__ import annotations

import bcrypt
import os
from dataclasses import dataclass

@dataclass
class UserSession:
    user_id: str
    role: str
    scopes: list[str]
    tenant_id: str

async def validate_token(raw_token: str) -> UserSession | None:
    """Validate bearer token against PostgreSQL (agent-twin pattern).

    For now, returns a mock user. In production, this connects to:
    - PostgreSQL with agent_tokens table (from agent-twin-mcp-server)
    - Uses bcrypt checkpw for validation
    - Caches via Redis for performance
    """
    # TODO: Connect to PostgreSQL and validate against agent_tokens table
    # For MVP, return a test user

    if raw_token == "test-admin-token":
        return UserSession(
            user_id="admin",
            role="admin",
            scopes=["*"],
            tenant_id="test",
        )

    if raw_token == "test-developer-token":
        return UserSession(
            user_id="dev1",
            role="developer",
            scopes=["qazilla-mcp", "backzilla-mcp"],
            tenant_id="test",
        )

    return None

async def authenticate_request(auth_header: str | None) -> UserSession | None:
    """Extract and validate Bearer token from Authorization header."""
    if not auth_header:
        return None

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    return await validate_token(token)
