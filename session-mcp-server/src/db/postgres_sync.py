"""
PostgreSQL Sync Layer para Session-MCP — Dual-write integration.

Estende SessionStore com sincronização para PostgreSQL durante a migração.
Mantém compatibilidade total com SQLite (fallback seguro).
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SessionPostgresSync:
    """
    Wrapper para sincronizar session-mcp com PostgreSQL.
    Usa MCPPostgreSQLAdapter como backend de sync.
    """

    def __init__(self, postgres_config: Dict[str, Any], enabled: bool = True):
        """
        Initialize sync layer.

        Args:
            postgres_config: PostgreSQL connection config (dbname, user, password, host, port)
            enabled: Se False, sync é desabilitado (fallback para SQLite apenas)
        """
        self.enabled = enabled
        self.postgres_config = postgres_config
        self.adapter = None

        if enabled:
            try:
                # Lazy import para evitar dependência circular
                sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "platform-service-template"))
                from lib.mcp_postgres_adapter import MCPPostgreSQLAdapter

                self.adapter = MCPPostgreSQLAdapter("session-mcp", postgres_config)
                logger.info("✅ SessionPostgresSync initialized (PostgreSQL enabled)")
            except Exception as e:
                logger.warning(f"⚠️  PostgreSQL sync disabled: {e}")
                self.enabled = False

    def close(self) -> None:
        """Close PostgreSQL connection."""
        if self.adapter:
            self.adapter.close()

    # ========== SESSION SYNC ==========

    def sync_session_created(self, session_data: Dict[str, Any]) -> bool:
        """Sync when new session is created."""
        if not self.enabled or not self.adapter:
            return True

        try:
            # Map SQLite fields to PostgreSQL schema
            pg_data = {
                'id': session_data['id'],
                'user_id': 1,  # Default admin user (will be linked from agent-twin later)
                'repository_id': session_data.get('repository_id'),
                'title': session_data['title'],
                'objective': session_data.get('objective', ''),
                'status': session_data.get('status', 'active'),
                'progress_percentage': 0,
                'created_at': session_data['started_at'],
                'last_activity_at': session_data['last_updated_at'],
            }

            self.adapter.sync_to_postgres('sessions', pg_data)
            logger.debug(f"Synced session created: {session_data['id']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync session created: {e}")
            return False

    def sync_session_updated(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Sync when session is updated."""
        if not self.enabled or not self.adapter:
            return True

        try:
            # Build SQL for partial update (only changed fields)
            set_clauses = []
            values = []

            field_map = {
                'status': 'status',
                'progress': 'progress_percentage',
                'last_updated_at': 'last_activity_at',
                'ended_at': 'completed_at',
            }

            for sqlite_field, pg_field in field_map.items():
                if sqlite_field in updates:
                    set_clauses.append(f"{pg_field} = %s")
                    values.append(updates[sqlite_field])

            if not set_clauses:
                return True

            values.append(session_id)
            sql = f"UPDATE sessions SET {', '.join(set_clauses)} WHERE id = %s"

            self.adapter.query_postgres(sql, tuple(values))
            logger.debug(f"Synced session updated: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync session updated: {e}")
            return False

    # ========== TASK SYNC ==========

    def sync_task_created(self, session_id: str, task_data: Dict[str, Any]) -> bool:
        """Sync when new task is created."""
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'session_id': session_id,
                'title': task_data['title'],
                'description': task_data.get('description', ''),
                'status': task_data.get('status', 'pending'),
                'owner_id': 1,  # Default admin
                'needs_human_decision': task_data.get('needs_human_decision', False),
                'created_at': task_data['created_at'],
                'started_at': task_data.get('started_at'),
                'completed_at': task_data.get('completed_at'),
            }

            self.adapter.sync_to_postgres('tasks', pg_data)
            logger.debug(f"Synced task created in session {session_id}: {task_data['title']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync task created: {e}")
            return False

    def sync_task_updated(self, task_id: int, updates: Dict[str, Any]) -> bool:
        """Sync when task is updated."""
        if not self.enabled or not self.adapter:
            return True

        try:
            field_map = {
                'status': 'status',
                'result': 'description',  # Map result to description for now
                'started_at': 'started_at',
                'completed_at': 'completed_at',
            }

            set_clauses = []
            values = []

            for sqlite_field, pg_field in field_map.items():
                if sqlite_field in updates:
                    set_clauses.append(f"{pg_field} = %s")
                    values.append(updates[sqlite_field])

            if not set_clauses:
                return True

            values.append(task_id)
            sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = %s"

            self.adapter.query_postgres(sql, tuple(values))
            logger.debug(f"Synced task updated: {task_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync task updated: {e}")
            return False

    # ========== CHECKPOINT SYNC ==========

    def sync_checkpoint_created(self, session_id: str, checkpoint_data: Dict[str, Any]) -> bool:
        """Sync when new checkpoint is created."""
        if not self.enabled or not self.adapter:
            return True

        try:
            import json

            pg_data = {
                'session_id': session_id,
                'summary': checkpoint_data['summary'],
                'context_snapshot': json.loads(checkpoint_data.get('context_json', '{}')),
                'created_by_id': 1,  # Default admin
                'created_at': checkpoint_data['created_at'],
            }

            self.adapter.sync_to_postgres('checkpoints', pg_data)
            logger.debug(f"Synced checkpoint created in session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync checkpoint created: {e}")
            return False

    # ========== ARTIFACT SYNC ==========

    def sync_artifact_created(self, session_id: str, artifact_data: Dict[str, Any]) -> bool:
        """Sync when new artifact is created."""
        if not self.enabled or not self.adapter:
            return True

        try:
            pg_data = {
                'session_id': session_id,
                'artifact_type': artifact_data['type'],
                'content': artifact_data['content'],
                'created_at': artifact_data['created_at'],
            }

            self.adapter.sync_to_postgres('artifacts', pg_data)
            logger.debug(f"Synced artifact created in session {session_id}: {artifact_data['type']}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync artifact created: {e}")
            return False

    # ========== AUDIT LOGGING ==========

    def log_action(self, action: str, target_type: str, target_id: str,
                   actor_id: Optional[int] = None, details: Optional[Dict] = None) -> bool:
        """Log action to audit_log (PostgreSQL)."""
        if not self.enabled or not self.adapter:
            return True

        try:
            self.adapter.audit_log(action, target_type, target_id, actor_id, details)
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
