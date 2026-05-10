"""
PostgreSQL Sync Layer para Pipeline-MCP — CI/CD pipeline and gate synchronization.

Estende pipeline-mcp para sincronizar pipelines, promotions e gates com PostgreSQL.
Cobre: register_pipeline, update_pipeline_env, block_pipeline, promotions, gate evaluations.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class PipelinePostgresSync:
    """
    Sincroniza pipelines, promotions e gates com PostgreSQL.
    Cobre: register_pipeline, promotions, gate evaluations, blockages.
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

                self.adapter = MCPPostgreSQLAdapter("pipeline-mcp", postgres_config)
                logger.info("✅ PipelinePostgresSync initialized (PostgreSQL enabled)")
            except Exception as e:
                logger.warning(f"⚠️  PostgreSQL sync disabled: {e}")
                self.enabled = False

    def close(self) -> None:
        """Close PostgreSQL connection."""
        if self.adapter:
            self.adapter.close()

    # ========== PIPELINE REGISTRATION SYNC ==========

    def sync_pipeline_registered(self, pipeline_data: Dict[str, Any]) -> bool:
        """
        Sync when pipeline is registered.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'service': pipeline_data['service'],
                'repo': pipeline_data['repo'],
                'base_branch': pipeline_data.get('base_branch', 'develop'),
                'current_env': pipeline_data.get('current_env', 'dev'),
                'current_version': pipeline_data.get('current_version'),
                'blocked': pipeline_data.get('blocked', False),
                'block_reason': pipeline_data.get('block_reason'),
                'gates_config': pipeline_data.get('gates_config', '{}'),
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'updated_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('pipelines', pg_data)
            logger.debug(f"Synced pipeline registered: {pipeline_data['service']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync pipeline registered: {e}")
            return False

    def sync_pipeline_env_updated(self, service: str, to_env: str, version: Optional[str] = None) -> bool:
        """
        Sync when pipeline is promoted to new environment.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE pipelines
            SET current_env = %s, current_version = %s, updated_at = NOW()
            WHERE service = %s
            """

            self.adapter.query_postgres(sql, (to_env, version, service))
            logger.debug(f"Synced pipeline env: {service} → {to_env}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync pipeline env: {e}")
            return False

    def sync_pipeline_blocked(self, service: str, reason: str, blocked_by: str) -> bool:
        """
        Sync when pipeline is blocked.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE pipelines
            SET blocked = true, block_reason = %s, blocked_by = %s,
                blocked_at = NOW(), updated_at = NOW()
            WHERE service = %s
            """

            self.adapter.query_postgres(sql, (reason, blocked_by, service))
            logger.debug(f"Synced pipeline blocked: {service}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync pipeline blocked: {e}")
            return False

    # ========== PROMOTION SYNC ==========

    def sync_promotion_created(self, promotion_data: Dict[str, Any]) -> bool:
        """
        Sync when promotion is created.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'service': promotion_data['service'],
                'from_env': promotion_data['from_env'],
                'to_env': promotion_data['to_env'],
                'promoted_by': promotion_data.get('promoted_by', 'system'),
                'reason': promotion_data.get('reason'),
                'gates_snapshot': promotion_data.get('gates_snapshot'),
                'deploy_ref': promotion_data.get('deploy_ref'),
                'pr_number': promotion_data.get('pr_number'),
                'pr_url': promotion_data.get('pr_url'),
                'status': promotion_data.get('status', 'pending'),
                'created_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('promotions', pg_data)
            logger.debug(f"Synced promotion: {promotion_data['service']} {promotion_data['from_env']}→{promotion_data['to_env']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync promotion: {e}")
            return False

    def sync_promotion_completed(self, promotion_id: int, status: str, completed_at: Optional[str] = None) -> bool:
        """
        Sync when promotion is completed.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE promotions
            SET status = %s, completed_at = %s
            WHERE id = %s
            """

            self.adapter.query_postgres(sql, (status, completed_at or datetime.utcnow().isoformat() + 'Z', promotion_id))
            logger.debug(f"Synced promotion completed: {promotion_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync promotion completed: {e}")
            return False

    def sync_promotion_approved(self, promotion_id: int, approved_by: str, approved_at: str) -> bool:
        """
        Sync when promotion is approved.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            sql = """
            UPDATE promotions
            SET approved_by = %s, approved_at = %s, status = 'approved'
            WHERE id = %s
            """

            self.adapter.query_postgres(sql, (approved_by, approved_at, promotion_id))
            logger.debug(f"Synced promotion approved: {promotion_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync promotion approved: {e}")
            return False

    # ========== GATE EVALUATION SYNC ==========

    def sync_gate_evaluated(self, service: str, env: str, gate_type: str, passed: bool, details: Optional[Dict] = None) -> bool:
        """
        Sync gate evaluation result.
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'service': service,
                'environment': env,
                'gate_type': gate_type,
                'passed': passed,
                'details': details,
                'evaluated_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.adapter.sync_to_postgres('gates', pg_data)
            logger.debug(f"Synced gate evaluated: {service}/{env}/{gate_type} → {'PASS' if passed else 'FAIL'}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync gate evaluated: {e}")
            return False

    # ========== QUERIES ==========

    def get_pipeline(self, service: str) -> Optional[Dict]:
        """
        Query PostgreSQL for pipeline.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM pipelines WHERE service = %s"
            results = self.adapter.query_postgres(sql, (service,))

            if results:
                logger.debug(f"Retrieved pipeline: {service}")
                return dict(results[0])
            return None

        except Exception as e:
            logger.error(f"Failed to get pipeline: {e}")
            return None

    def list_promotions(self, service: Optional[str] = None, status: Optional[str] = None) -> Optional[list]:
        """
        Query PostgreSQL for promotions.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM promotions WHERE 1=1"
            params = []

            if service:
                sql += " AND service = %s"
                params.append(service)

            if status:
                sql += " AND status = %s"
                params.append(status)

            sql += " ORDER BY created_at DESC"

            results = self.adapter.query_postgres(sql, tuple(params) if params else None)
            logger.debug(f"Listed promotions ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to list promotions: {e}")
            return None

    def get_gates(self, service: str, env: str) -> Optional[list]:
        """
        Query PostgreSQL for gate evaluations.
        """
        if not self.enabled or not self.adapter:
            return None

        try:
            sql = "SELECT * FROM gates WHERE service = %s AND environment = %s ORDER BY gate_type"
            results = self.adapter.query_postgres(sql, (service, env))
            logger.debug(f"Retrieved gates ({len(results) if results else 0} found)")
            return results

        except Exception as e:
            logger.error(f"Failed to get gates: {e}")
            return None

    # ========== AUDIT LOGGING ==========

    def log_action(self, action: str, service: str,
                   actor_id: Optional[int] = None, details: Optional[Dict] = None) -> bool:
        """
        Log pipeline action to audit_log.

        Actions: register, promote, block, approve, evaluate_gate
        """
        if not self.enabled or not self.adapter:
            return True

        try:
            self.adapter.audit_log(
                action=action,
                target_type='pipeline',
                target_id=service,
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
