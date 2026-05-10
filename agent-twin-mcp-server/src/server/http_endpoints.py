"""
Agent-Twin-MCP HTTP Endpoints — PostgreSQL Integration.

Endpoints para sincronizar identidade e login com PostgreSQL.
"""

from typing import Dict, Any, Optional
import logging
from datetime import datetime
import json

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
        """Authenticate user against SQLite token store."""
        # TODO: Implement actual authentication logic
        # For now, return mock user
        return {
            'id': 1,
            'email': email,
            'name': 'Test User',
            'role': 'developer',
            'tenant_id': 'platform_dev'
        }

    def _generate_token(self, user: Dict) -> str:
        """Generate long-lived user token."""
        # TODO: Implement token generation
        return f"tkn_{user['id']}_{int(datetime.utcnow().timestamp())}"

    def _generate_session_token(self, user: Dict) -> str:
        """Generate ephemeral session token."""
        # TODO: Implement session token generation
        return f"sess_tkn_{user['id']}_{int(datetime.utcnow().timestamp())}"

    def _validate_token(self, token: str) -> Optional[Dict]:
        """Validate token against SQLite token store."""
        # TODO: Implement token validation
        return None

    def _revoke_token(self, token: str) -> bool:
        """Revoke token in SQLite."""
        # TODO: Implement token revocation
        return True
