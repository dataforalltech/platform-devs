"""
PostgreSQL Sync Layer para Audit-MCP — Audit data synchronization.

Estende audit-mcp para sincronizar dados de auditoria com PostgreSQL.
Cobre: create_audit, update_audit_status, add_audit_item, add_approval, set_service_criticality.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class AuditPostgresSync:
    """
    Sincroniza dados de auditoria com PostgreSQL.
    Cobre: audits, audit_items, audit_approvals, service_criticality.
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

                self.adapter = MCPPostgreSQLAdapter("audit-mcp", postgres_config)
                logger.info("✅ AuditPostgresSync initialized (PostgreSQL enabled)")
            except Exception as e:
                logger.warning(f"⚠️  PostgreSQL sync disabled: {e}")
                self.enabled = False

    def close(self) -> None:
        """Close PostgreSQL connection."""
        if self.adapter:
            self.adapter.close()

    # ========== AUDIT RECORD SYNC ==========

    def sync_audit_created(self, audit_data: Dict[str, Any]) -> bool:
        """
        Sync when audit record is created.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'id': audit_data['id'],
                'service': audit_data['service'],
                'repo': audit_data.get('repo', ''),
                'environment': audit_data.get('env', 'unknown'),
                'criticality': audit_data.get('criticality', 'medium'),
                'score': float(audit_data.get('score', 0)),
                'passed': audit_data.get('passed', False),
                'status': audit_data.get('status', 'pending'),
                'checklist_data': audit_data.get('checklist', '{}'),
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'updated_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('audits', pg_data)
            logger.debug(f"Synced audit created: {audit_data['id']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync audit created: {e}")
            return False

    def sync_audit_updated(self, audit_id: str, updates: Dict[str, Any]) -> bool:
        """
        Sync when audit is updated (status, score, passed).
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            set_clauses = []
            values = []

            if 'status' in updates:
                set_clauses.append("status = %s")
                values.append(updates['status'])

            if 'score' in updates:
                set_clauses.append("score = %s")
                values.append(float(updates['score']))

            if 'passed' in updates:
                set_clauses.append("passed = %s")
                values.append(updates['passed'])

            if not set_clauses:
                return True

            set_clauses.append("updated_at = NOW()")
            values.append(audit_id)

            sql = f"UPDATE audits SET {', '.join(set_clauses)} WHERE id = %s"
            self.adapter.query_postgres(sql, tuple(values))
            logger.debug(f"Synced audit updated: {audit_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync audit updated: {e}")
            return False

    # ========== AUDIT ITEM SYNC ==========

    def sync_audit_item_added(self, audit_id: str, item_data: Dict[str, Any]) -> bool:
        """
        Sync when audit item is added.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'audit_id': audit_id,
                'category': item_data.get('category', ''),
                'name': item_data.get('name', ''),
                'required': item_data.get('required', False),
                'passed': item_data.get('passed', False),
                'details': item_data.get('details'),
                'created_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('audit_items', pg_data)
            logger.debug(f"Synced audit item: {audit_id}/{item_data.get('name')}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync audit item: {e}")
            return False

    # ========== APPROVAL SYNC ==========

    def sync_approval_added(self, audit_id: str, approval_data: Dict[str, Any]) -> bool:
        """
        Sync when approval is added.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'audit_id': audit_id,
                'approved_by': approval_data.get('approved_by', ''),
                'role': approval_data.get('role'),
                'decision': approval_data.get('decision', 'pending'),
                'notes': approval_data.get('notes'),
                'created_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('audit_approvals', pg_data)
            logger.debug(f"Synced approval: {audit_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync approval: {e}")
            return False

    # ========== SERVICE CRITICALITY SYNC ==========

    def sync_service_criticality(self, service: str, criticality: str, updated_by: str) -> bool:
        """
        Sync when service criticality is set.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'service': service,
                'criticality': criticality,
                'updated_by': updated_by,
                'updated_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('service_criticality', pg_data)
            logger.debug(f"Synced service criticality: {service} → {criticality}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync service criticality: {e}")
            return False

    # ========== QUERIES ==========

    def get_audit(self, audit_id: str) -> Optional[Dict]:
        """
        Query PostgreSQL for audit record.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM audits WHERE id = %s"
            results = self.adapter.query_postgres(sql, (audit_id,))

            if results:
                logger.debug(f"Retrieved audit: {audit_id}")
                return dict(results[0])
            return None

        except Exception as e:
            logger.error(f"Failed to get audit: {e}")
            return None

    def list_audits(self, service: Optional[str] = None, environment: Optional[str] = None) -> Optional[list]:
        """
        Query PostgreSQL for audits.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM audits WHERE 1=1"
            params = []

            if service:
                sql += " AND service = %s"
                params.append(service)

            if environment:
                sql += " AND environment = %s"
                params.append(environment)

            sql += " ORDER BY created_at DESC"

            results = self.adapter.query_postgres(sql, tuple(params) if params else None)
            logger.debug(f"Listed audits ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to list audits: {e}")
            return None

    def get_audit_items(self, audit_id: str) -> Optional[list]:
        """
        Query PostgreSQL for audit items.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM audit_items WHERE audit_id = %s ORDER BY category, name"
            results = self.adapter.query_postgres(sql, (audit_id,))
            logger.debug(f"Retrieved audit items ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to get audit items: {e}")
            return None

    def get_approvals(self, audit_id: str) -> Optional[list]:
        """
        Query PostgreSQL for audit approvals.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM audit_approvals WHERE audit_id = %s ORDER BY created_at DESC"
            results = self.adapter.query_postgres(sql, (audit_id,))
            logger.debug(f"Retrieved approvals ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to get approvals: {e}")
            return None

    # ========== AUDIT LOGGING ==========

    def log_action(self, action: str, audit_id: str,
                   actor_id: Optional[int] = None, details: Optional[Dict] = None) -> bool:
        """
        Log audit action to audit_log.

        Actions: create, update, approve, reject, review
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            self.adapter.audit_log(
                action=action,
                target_type='audit',
                target_id=audit_id,
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
