"""
PostgreSQL Sync Layer para Services-MCP — Service registry synchronization.

Estende services-mcp para sincronizar registro de serviços e health status com PostgreSQL.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ServicesPostgresSync:
    """
    Sincroniza registry de serviços com PostgreSQL.
    Cobre: register_service, update_service_status, health_checks.
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

                self.adapter = MCPPostgreSQLAdapter("services-mcp", postgres_config)
                logger.info("✅ ServicesPostgresSync initialized (PostgreSQL enabled)")
            except Exception as e:
                logger.warning(f"⚠️  PostgreSQL sync disabled: {e}")
                self.enabled = False

    def close(self) -> None:
        """Close PostgreSQL connection."""
        if self.adapter:
            self.adapter.close()

    # ========== SERVICE REGISTRATION SYNC ==========

    def sync_service_registered(self, service_data: Dict[str, Any]) -> bool:
        """
        Sync when service is registered.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'name': service_data['name'],
                'type': service_data.get('type', 'unknown'),
                'host': service_data.get('host', 'localhost'),
                'port': service_data.get('port'),
                'description': service_data.get('description', ''),
                'health_check_url': service_data.get('health_check_url'),
                'endpoint': service_data.get('endpoint'),
                'status': 'unknown',  # Will be updated by first health check
                'environment': service_data.get('environment', 'dev'),
                'requires_auth': service_data.get('requires_auth', False),
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'updated_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('services', pg_data)
            logger.debug(f"Synced service registered: {service_data['name']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync service registered: {e}")
            return False

    def sync_service_updated(self, service_name: str, updates: Dict[str, Any]) -> bool:
        """
        Sync when service metadata is updated.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            field_map = {
                'description': 'description',
                'health_check_url': 'health_check_url',
                'endpoint': 'endpoint',
                'environment': 'environment',
                'requires_auth': 'requires_auth',
            }

            set_clauses = []
            values = []

            for source_field, pg_field in field_map.items():
                if source_field in updates:
                    set_clauses.append(f"{pg_field} = %s")
                    values.append(updates[source_field])

            if not set_clauses:
                return True

            set_clauses.append("updated_at = NOW()")
            values.append(service_name)

            sql = f"UPDATE services SET {', '.join(set_clauses)} WHERE name = %s"
            self.adapter.query_postgres(sql, tuple(values))
            logger.debug(f"Synced service updated: {service_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync service updated: {e}")
            return False

    # ========== HEALTH STATUS SYNC ==========

    def sync_health_check_result(self, service_name: str, status: str, response_time_ms: Optional[float] = None) -> bool:
        """
        Sync health check result.

        Args:
            service_name: Name of service
            status: 'healthy', 'unhealthy', 'unknown', 'offline'
            response_time_ms: Response time in milliseconds (optional)
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE services
            SET status = %s, last_health_check_at = NOW(), updated_at = NOW()
            WHERE name = %s
            """

            self.adapter.query_postgres(sql, (status, service_name))
            logger.debug(f"Synced health check: {service_name} → {status}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync health check: {e}")
            return False

    # ========== SERVICE UNREGISTRATION SYNC ==========

    def sync_service_removed(self, service_name: str) -> bool:
        """
        Sync when service is removed from registry.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = "DELETE FROM services WHERE name = %s"
            self.adapter.query_postgres(sql, (service_name,))
            logger.debug(f"Synced service removed: {service_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync service removed: {e}")
            return False

    # ========== QUERIES ==========

    def list_services(self, environment: Optional[str] = None, status: Optional[str] = None) -> Optional[list]:
        """
        Query PostgreSQL for services.

        Args:
            environment: Filter by environment ('dev', 'staging', 'prod')
            status: Filter by status ('healthy', 'unhealthy', 'unknown', 'offline')

        Returns:
            List of service records or None on error
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM services WHERE 1=1"
            params = []

            if environment:
                sql += " AND environment = %s"
                params.append(environment)

            if status:
                sql += " AND status = %s"
                params.append(status)

            sql += " ORDER BY name"

            results = self.adapter.query_postgres(sql, tuple(params) if params else None)
            logger.debug(f"Listed services ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to list services: {e}")
            return None

    def get_service(self, service_name: str) -> Optional[Dict]:
        """
        Query PostgreSQL for single service.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM services WHERE name = %s"
            results = self.adapter.query_postgres(sql, (service_name,))

            if results:
                logger.debug(f"Retrieved service: {service_name}")
                return dict(results[0])
            return None

        except Exception as e:
            logger.error(f"Failed to get service: {e}")
            return None

    def list_unhealthy_services(self) -> Optional[list]:
        """
        Query for all unhealthy services.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM services WHERE status IN ('unhealthy', 'offline') ORDER BY last_health_check_at DESC"
            results = self.adapter.query_postgres(sql)
            logger.debug(f"Listed unhealthy services ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to list unhealthy services: {e}")
            return None

    # ========== AUDIT LOGGING ==========

    def log_action(self, action: str, service_name: str,
                   actor_id: Optional[int] = None, details: Optional[Dict] = None) -> bool:
        """
        Log service action to audit_log.

        Actions: register, update, health_check, unregister, status_change
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            self.adapter.audit_log(
                action=action,
                target_type='service',
                target_id=service_name,
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
