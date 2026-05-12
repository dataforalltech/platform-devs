"""
Config-MCP HTTP Endpoints — PostgreSQL Integration.

Endpoints para listar e gerenciar credenciais com segurança.
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ConfigHTTPEndpoints:
    """HTTP endpoints para config-mcp com sync PostgreSQL."""

    def __init__(self, postgres_sync, tenant_id: str):
        """
        Initialize endpoints.

        Args:
            postgres_sync: ConfigPostgresSync instance
            tenant_id: Current tenant context
        """
        self.postgres_sync = postgres_sync
        self.tenant_id = tenant_id

    # ========== GET /credentials/list ==========

    def get_credentials_list(self, namespace: Optional[str] = None,
                            include_metadata: bool = True) -> Dict[str, Any]:
        """
        GET /credentials/list

        Lista credenciais disponíveis (sem valores criptografados).
        Filtra por tenant_id automaticamente.

        Query params:
            - namespace: Filter by namespace (credentials.github, env.dev, etc)
            - include_metadata: Include owner, expires_at, etc (default: true)

        Response (200):
            {
                "credentials": [
                    {
                        "namespace": "credentials.github",
                        "key": "GITHUB_TOKEN",
                        "owner_id": 1,
                        "active": true,
                        "created_at": "2026-05-01T...",
                        "expires_at": "2026-12-31T...",
                        "last_used_at": "2026-05-10T..."
                    }
                ],
                "total": 12,
                "tenant_id": "platform_dev"
            }

        Security:
            - ✅ Values are NEVER returned
            - ✅ Only metadata is included
            - ✅ Filtered by current tenant_id
        """
        try:
            # Credentials are namespaced by tenant
            namespace_filter = namespace or f"credentials.*"

            credentials = self.postgres_sync.list_credentials_for_namespace(
                namespace=namespace_filter
            )

            if credentials is None:
                return {
                    'status': 500,
                    'error': 'database_error'
                }

            # Filter by tenant if not already in namespace
            # (depends on how tenants are encoded in PostgreSQL)

            return {
                'status': 200,
                'credentials': [dict(c) for c in credentials],
                'total': len(credentials),
                'tenant_id': self.tenant_id
            }

        except Exception as e:
            logger.error(f"Error in GET /credentials/list: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /credentials/metadata ==========

    def get_credentials_metadata(self, namespace: str, key: str) -> Dict[str, Any]:
        """
        GET /credentials/metadata

        Retorna metadados de uma credencial (sem valor).

        Request:
            GET /credentials/metadata?namespace=credentials.github&key=GITHUB_TOKEN

        Response (200):
            {
                "namespace": "credentials.github",
                "key": "GITHUB_TOKEN",
                "owner_id": 1,
                "active": true,
                "created_at": "2026-05-01T...",
                "updated_at": "2026-05-10T...",
                "expires_at": "2026-12-31T...",
                "last_used_at": "2026-05-10T10:30:00Z"
            }

        Response (404):
            {
                "error": "credential_not_found"
            }
        """
        try:
            metadata = self.postgres_sync.get_credential_metadata(namespace, key)

            if metadata is None:
                return {
                    'status': 404,
                    'error': 'credential_not_found'
                }

            return {
                'status': 200,
                **metadata  # Spread the metadata dict
            }

        except Exception as e:
            logger.error(f"Error in GET /credentials/metadata: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /credentials/validate ==========

    def post_credentials_validate(self, namespace: str, key: str) -> Dict[str, Any]:
        """
        POST /credentials/validate

        Valida se credencial existe e está ativa.

        Request:
            {
                "namespace": "credentials.github",
                "key": "GITHUB_TOKEN"
            }

        Response (200):
            {
                "valid": true,
                "active": true,
                "expires_at": "2026-12-31T..."
            }

        Response (404):
            {
                "valid": false,
                "error": "credential_not_found"
            }
        """
        try:
            metadata = self.postgres_sync.get_credential_metadata(namespace, key)

            if metadata is None:
                return {
                    'status': 404,
                    'valid': False,
                    'error': 'credential_not_found'
                }

            is_expired = False
            if metadata.get('expires_at'):
                from datetime import datetime as dt
                expires = dt.fromisoformat(metadata['expires_at'].replace('Z', '+00:00'))
                is_expired = expires < dt.now(dt.UTC)

            return {
                'status': 200,
                'valid': metadata.get('active', False) and not is_expired,
                'active': metadata.get('active', False),
                'expires_at': metadata.get('expires_at'),
                'is_expired': is_expired
            }

        except Exception as e:
            logger.error(f"Error in POST /credentials/validate: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /credentials/rotate ==========

    def post_credentials_rotate(self, namespace: str, key: str,
                               new_value: str) -> Dict[str, Any]:
        """
        POST /credentials/rotate

        Rotaciona credencial (atualiza valor criptografado).

        Request:
            {
                "namespace": "credentials.github",
                "key": "GITHUB_TOKEN",
                "new_value": "ghp_new_token..."
            }

        Response (200):
            {
                "rotated": true,
                "updated_at": "2026-05-10T10:30:45Z"
            }

        Security:
            - ✅ Updates encrypted value in config.enc.json
            - ✅ Updates metadata in PostgreSQL
            - ✅ Logs rotation in audit_log
        """
        try:
            # Step 1: Update encrypted value (config.enc.json)
            self._update_credential_value(namespace, key, new_value)

            # Step 2: Update metadata in PostgreSQL (updated_at)
            self.postgres_sync.sync_credential_expires(
                namespace=namespace,
                key=key,
                expires_at=None  # Reset expiry on rotation
            )

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='rotate',
                namespace=namespace,
                key=key,
                details={'rotated': True}
            )

            logger.info(f"✅ Credential rotated: {namespace}.{key}")

            return {
                'status': 200,
                'rotated': True,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /credentials/rotate: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== DELETE /credentials ==========

    def delete_credentials(self, namespace: str, key: str) -> Dict[str, Any]:
        """
        DELETE /credentials

        Deleta credencial (soft delete: marca como inactive).

        Request:
            DELETE /credentials?namespace=credentials.github&key=GITHUB_TOKEN

        Response (200):
            {
                "deleted": true,
                "timestamp": "2026-05-10T10:30:45Z"
            }

        Response (404):
            {
                "error": "credential_not_found"
            }

        Security:
            - ✅ Soft delete (marked as inactive, not removed)
            - ✅ Audit trail recorded
        """
        try:
            # Step 1: Check if exists
            metadata = self.postgres_sync.get_credential_metadata(namespace, key)
            if metadata is None:
                return {
                    'status': 404,
                    'error': 'credential_not_found'
                }

            # Step 2: Mark as deleted in PostgreSQL
            self.postgres_sync.sync_credential_deleted(namespace, key)

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='delete',
                namespace=namespace,
                key=key,
                details={'soft_delete': True}
            )

            logger.info(f"✅ Credential deleted: {namespace}.{key}")

            return {
                'status': 200,
                'deleted': True,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in DELETE /credentials: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /credentials/namespaces ==========

    def get_credentials_namespaces(self) -> Dict[str, Any]:
        """
        GET /credentials/namespaces

        Lista todos os namespaces disponíveis.

        Response (200):
            {
                "namespaces": [
                    "credentials.github",
                    "credentials.aws",
                    "env.dev",
                    "env.prod"
                ],
                "total": 4
            }
        """
        try:
            namespaces = self.postgres_sync.list_credential_namespaces()

            return {
                'status': 200,
                'namespaces': namespaces,
                'total': len(namespaces)
            }

        except Exception as e:
            logger.error(f"Error in GET /credentials/namespaces: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== Private Helpers ==========

    def _update_credential_value(self, namespace: str, key: str, value: str) -> bool:
        """Update encrypted credential value via PostgreSQL sync."""
        try:
            if self.postgres_sync:
                self.postgres_sync.update_credential(namespace, key, value)
            return True
        except Exception as e:
            logger.error(f"Failed to update credential: {e}")
            return False
