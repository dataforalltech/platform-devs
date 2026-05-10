"""
PostgreSQL Sync Layer para Config-MCP — Credentials metadata synchronization.

Estende config-mcp com sincronização de metadados de credenciais para PostgreSQL.
Valores criptografados permanecem em config.enc.json (não vão para PostgreSQL).
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ConfigPostgresSync:
    """
    Sincroniza metadados de credenciais com PostgreSQL.
    Valores encriptados ficam em config.enc.json.
    Metadados (namespace, key, owner, active, expires_at) vão para PostgreSQL.
    """

    def __init__(self, postgres_config: Dict[str, Any], enabled: bool = True):
        """
        Initialize sync layer.

        Args:
            postgres_config: PostgreSQL connection config
            enabled: Se False, sync é desabilitado
        """
        self.enabled = enabled
        self.postgres_config = postgres_config
        self.adapter = None

        if enabled:
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "platform-service-template"))
                from lib.mcp_postgres_adapter import MCPPostgreSQLAdapter

                self.adapter = MCPPostgreSQLAdapter("config-mcp", postgres_config)
                logger.info("✅ ConfigPostgresSync initialized (PostgreSQL enabled)")
            except Exception as e:
                logger.warning(f"⚠️  PostgreSQL sync disabled: {e}")
                self.enabled = False

    def close(self) -> None:
        """Close PostgreSQL connection."""
        if self.adapter:
            self.adapter.close()

    # ========== CREDENTIAL METADATA SYNC ==========

    def sync_credential_created(self, namespace: str, key: str,
                                owner_id: Optional[int] = None,
                                expires_at: Optional[str] = None) -> bool:
        """
        Sync when credential metadata is created.

        Note: The actual encrypted value stays in config.enc.json.
        We only sync metadata to PostgreSQL.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'namespace': namespace,
                'key': key,
                'owner_id': owner_id,
                'active': True,
                'expires_at': expires_at,
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'updated_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('credentials', pg_data)
            logger.debug(f"Synced credential metadata: {namespace}.{key}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync credential created: {e}")
            return False

    def sync_credential_used(self, namespace: str, key: str) -> bool:
        """
        Sync when credential is used (update last_used_at).
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE credentials
            SET last_used_at = NOW()
            WHERE namespace = %s AND key = %s
            """

            self.adapter.query_postgres(sql, (namespace, key))
            logger.debug(f"Updated last_used_at: {namespace}.{key}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync credential used: {e}")
            return False

    def sync_credential_deleted(self, namespace: str, key: str) -> bool:
        """
        Sync when credential is deleted (mark as inactive or remove).
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE credentials
            SET active = false, updated_at = NOW()
            WHERE namespace = %s AND key = %s
            """

            self.adapter.query_postgres(sql, (namespace, key))
            logger.debug(f"Marked credential as inactive: {namespace}.{key}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync credential deleted: {e}")
            return False

    def sync_credential_expires(self, namespace: str, key: str, expires_at: str) -> bool:
        """
        Sync when credential expiration is updated.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE credentials
            SET expires_at = %s, updated_at = NOW()
            WHERE namespace = %s AND key = %s
            """

            self.adapter.query_postgres(sql, (expires_at, namespace, key))
            logger.debug(f"Updated credential expiration: {namespace}.{key}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync credential expiration: {e}")
            return False

    # ========== QUERIES ==========

    def list_credentials_for_namespace(self, namespace: str) -> Optional[list]:
        """
        Query PostgreSQL for all credentials in a namespace.
        Returns metadata only (not encrypted values).
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = """
            SELECT namespace, key, owner_id, active, created_at, expires_at, last_used_at
            FROM credentials
            WHERE namespace = %s AND active = true
            ORDER BY key
            """

            results = self.adapter.query_postgres(sql, (namespace,))
            logger.debug(f"Listed credentials for namespace: {namespace} ({len(results)} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            return None

    def get_credential_metadata(self, namespace: str, key: str) -> Optional[Dict]:
        """
        Query PostgreSQL for credential metadata (not the value).
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = """
            SELECT namespace, key, owner_id, active, created_at, updated_at, expires_at, last_used_at
            FROM credentials
            WHERE namespace = %s AND key = %s
            """

            results = self.adapter.query_postgres(sql, (namespace, key))
            if results:
                logger.debug(f"Retrieved metadata for: {namespace}.{key}")
                return dict(results[0])
            return None

        except Exception as e:
            logger.error(f"Failed to get credential metadata: {e}")
            return None

    # ========== AUDIT LOGGING ==========

    def log_action(self, action: str, namespace: str, key: str,
                   actor_id: Optional[int] = None, details: Optional[Dict] = None) -> bool:
        """
        Log credential action to audit_log.

        Actions: create, update, delete, access, rotate, revoke
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            target_id = f"{namespace}.{key}"
            self.adapter.audit_log(
                action=action,
                target_type='credential',
                target_id=target_id,
                actor_id=actor_id,
                details=details or {}
            )
            return True

        except Exception as e:
            logger.error(f"Failed to log action: {e}")
            return False

    # ========== HEALTH CHECK ==========

    def health_check(self) -> bool:
        """Check PostgreSQL connection health."""
        if not self.enabled or not self.adapter:
            return True

        try:
            return self.adapter.health_check()
        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
            return False
