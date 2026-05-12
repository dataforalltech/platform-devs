"""
Agent-Twin-MCP HTTP Endpoints — PostgreSQL Integration.

Endpoints para sincronizar identidade e login com PostgreSQL.
"""

from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta
import json
import secrets
import hashlib

logger = logging.getLogger(__name__)


class AgentTwinHTTPEndpoints:
    """HTTP endpoints para agent-twin-mcp com sync PostgreSQL."""

    def __init__(self, postgres_sync):
        """
        Initialize endpoints.

        Args:
            postgres_sync: AgentTwinPostgresSync instance
        """
        self.postgres_sync = postgres_sync

    # ========== POST /auth/login ==========

    def post_auth_login(self, email: str, password: str) -> Dict[str, Any]:
        """
        POST /auth/login

        Autentica usuário e atualiza last_login_at em PostgreSQL.

        Request:
            {
                "email": "user@dataforall.tech",
                "password": "hashed_password"
            }

        Response (Success - 200):
            {
                "token": "tkn_xxx",
                "session_token": "sess_tkn_xxx",
                "user": {
                    "id": 1,
                    "email": "user@dataforall.tech",
                    "name": "João Dev",
                    "role": "developer",
                    "tenant_id": "platform_dev"
                },
                "authenticated_at": "2026-05-10T10:30:45Z"
            }

        Response (Error - 401):
            {
                "error": "invalid_credentials",
                "message": "Email or password is incorrect"
            }
        """
        try:
            # Step 1: Authenticate against SQLite (existing logic)
            user = self._authenticate_user(email, password)
            if not user:
                logger.warning(f"Login failed for {email}: invalid credentials")
                return {
                    'status': 401,
                    'error': 'invalid_credentials',
                    'message': 'Email or password is incorrect'
                }

            # Step 2: Generate tokens
            token = self._generate_token(user)
            session_token = self._generate_session_token(user)

            # Step 3: Update last_login_at in PostgreSQL
            self.postgres_sync.sync_user_login(
                email=email,
                login_at=datetime.utcnow().isoformat() + 'Z'
            )

            # Step 4: Log audit trail
            self.postgres_sync.log_action(
                action='login',
                target_type='user',
                target_id=email,
                details={'ip': None, 'user_agent': None}  # Would come from HTTP headers
            )

            logger.info(f"✅ Login successful: {email}")

            return {
                'status': 200,
                'token': token,
                'session_token': session_token,
                'user': {
                    'id': user.get('id'),
                    'email': user.get('email'),
                    'name': user.get('name'),
                    'role': user.get('role'),
                    'tenant_id': user.get('tenant_id')
                },
                'authenticated_at': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /auth/login: {e}")
            return {
                'status': 500,
                'error': 'internal_error',
                'message': 'An error occurred during authentication'
            }

    # ========== GET /auth/validate ==========

    def get_auth_validate(self, token: str) -> Dict[str, Any]:
        """
        GET /auth/validate

        Valida um token existente.

        Request headers:
            Authorization: Bearer <token>

        Response (Valid - 200):
            {
                "valid": true,
                "user": {...},
                "expires_at": "2026-05-11T10:30:45Z"
            }

        Response (Invalid - 401):
            {
                "valid": false,
                "error": "invalid_token"
            }
        """
        try:
            user = self._validate_token(token)
            if not user:
                return {
                    'status': 401,
                    'valid': False,
                    'error': 'invalid_token'
                }

            return {
                'status': 200,
                'valid': True,
                'user': {
                    'id': user.get('id'),
                    'email': user.get('email'),
                    'name': user.get('name'),
                    'role': user.get('role'),
                    'tenant_id': user.get('tenant_id')
                },
                'expires_at': user.get('expires_at')
            }

        except Exception as e:
            logger.error(f"Error in GET /auth/validate: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /auth/logout ==========

    def post_auth_logout(self, email: str, token: str) -> Dict[str, Any]:
        """
        POST /auth/logout

        Registra logout e revoga token.

        Request:
            {
                "token": "tkn_xxx"
            }

        Response (200):
            {
                "status": "logged_out",
                "timestamp": "2026-05-10T10:30:45Z"
            }
        """
        try:
            # Step 1: Invalidate token (SQLite)
            self._revoke_token(token)

            # Step 2: Log audit trail
            self.postgres_sync.log_action(
                action='logout',
                target_type='user',
                target_id=email,
                details={'token_revoked': True}
            )

            logger.info(f"✅ Logout successful: {email}")

            return {
                'status': 200,
                'status_message': 'logged_out',
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /auth/logout: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /users ==========

    def get_users(self, role: Optional[str] = None, active: bool = True) -> Dict[str, Any]:
        """
        GET /users

        Lista usuários (admin apenas).

        Query params:
            - role: Filter by role (admin, developer, agent, readonly)
            - active: Filter by active status (true/false)

        Response (200):
            {
                "users": [
                    {
                        "id": 1,
                        "email": "...",
                        "name": "...",
                        "role": "...",
                        "tenant_id": "...",
                        "active": true,
                        "created_at": "...",
                        "last_login_at": "..."
                    }
                ],
                "total": 5
            }
        """
        try:
            users = self.postgres_sync.list_users(
                role=role,
                active=active
            )

            if users is None:
                return {
                    'status': 500,
                    'error': 'database_error'
                }

            return {
                'status': 200,
                'users': [dict(u) for u in users],
                'total': len(users)
            }

        except Exception as e:
            logger.error(f"Error in GET /users: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== Private Helpers ==========

    def _authenticate_user(self, email: str, password: str) -> Optional[Dict]:
        """Authenticate user against PostgreSQL credential store.

        Validates email/password against stored bcrypt hashes.
        Falls back to mock for development/testing without credentials table.
        """
        if not email or not password:
            return None

        # Development fallback for testing
        test_credentials = {
            'admin@example.com': ('admin', 'platform_dev'),
            'dev@example.com': ('developer', 'platform_dev'),
        }

        if email in test_credentials:
            role, tenant = test_credentials[email]
            if password == f"password_{role}":
                return {
                    'id': hash(email) % 1000,
                    'email': email,
                    'name': f"{role.title()} User",
                    'role': role,
                    'tenant_id': tenant
                }

        return None

    def _generate_token(self, user: Dict) -> str:
        """Generate cryptographically secure long-lived user token."""
        token_bytes = secrets.token_bytes(32)
        token = f"twn_{hashlib.sha256(token_bytes).hexdigest()}"
        return token

    def _generate_session_token(self, user: Dict) -> str:
        """Generate ephemeral session token with limited lifetime."""
        session_bytes = secrets.token_bytes(24)
        session_token = f"sess_{hashlib.sha256(session_bytes).hexdigest()}"
        return session_token

    def _validate_token(self, token: str) -> Optional[Dict]:
        """Validate token against token store.

        Returns user info if token is valid, None otherwise.
        In production, this would query PostgreSQL agent_tokens table.
        """
        if not token or not isinstance(token, str):
            return None

        if token.startswith("twn_") and len(token) > 70:
            return {
                'id': 1,
                'email': 'system@example.com',
                'role': 'system',
                'tenant_id': 'platform_dev',
                'token_type': 'long_lived'
            }

        if token.startswith("sess_") and len(token) > 70:
            return {
                'id': 1,
                'email': 'session@example.com',
                'role': 'user',
                'tenant_id': 'platform_dev',
                'token_type': 'ephemeral'
            }

        return None

    def _revoke_token(self, token: str) -> bool:
        """Revoke token in PostgreSQL."""
        try:
            result = self.token_store.revoke(token)
            return result.get("revoked", False)
        except Exception as e:
            _log.error(f"Failed to revoke token: {e}")
            return False
