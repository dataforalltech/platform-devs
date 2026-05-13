"""SessionStore — persistência PostgreSQL thread-safe para sessões de trabalho Claude Code.

Cinco tabelas principais:
  sessions      — registro de cada sessão
  checkpoints   — snapshots do progresso salvos ao longo da sessão
  artifacts     — eventos relevantes (arquivos alterados, decisões, tool calls)
  tasks         — tarefas planejadas/executadas dentro da sessão
  suggestions   — fila cross-repo: repo X sugere algo para repo Y trabalhar
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from ..config.settings import SessionSettings

logger = logging.getLogger(__name__)

TASK_STATUSES = ("pending", "in_progress", "completed", "failed", "cancelled")
TASK_OPEN_STATUSES = ("pending", "in_progress")
TASK_TERMINAL_STATUSES = ("completed", "failed", "cancelled")

SUGGESTION_STATUSES = ("pending", "accepted", "rejected", "deferred", "superseded")
SUGGESTION_KINDS = ("improvement", "correction", "addition", "question", "other")
SUGGESTION_PRIORITIES = ("low", "medium", "high", "critical")

ACTOR_TYPES = ("human", "agent", "system")


def _generate_name() -> str:
    """Gera um nome único para a sessão."""
    adjectives = ["ancient", "blazing", "bold", "calm", "cosmic", "clever", "daring", "divine"]
    names = ["zeus", "odin", "athena", "batman", "marvel", "goku", "loki", "thor"]
    return f"{random.choice(adjectives)}-{random.choice(names)}"


def _now() -> str:
    """Retorna ISO timestamp com timezone."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Gera UUID v4 truncado para 32 chars (PG limit)."""
    return str(uuid.uuid4()).replace("-", "")[:32]


class SessionStore:
    """PostgreSQL thread-safe session store com connection pool."""

    def __init__(self, settings: SessionSettings) -> None:
        self.settings = settings
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pg_min_conn,
            maxconn=settings.pg_max_conn,
            dsn=settings.pg_dsn,
        )
        logger.info(f"✅ SessionStore initialized with PostgreSQL pool ({settings.pg_min_conn}-{settings.pg_max_conn} connections)")

    @contextmanager
    def _get_conn(self):
        """Context manager para obter conexão do pool."""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        """Fecha o connection pool."""
        if self._pool:
            self._pool.closeall()
            logger.info("SessionStore connection pool closed")

    # ────────────────────────────────────────────────────────────────────────── #
    # SESSION OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def create_session(
        self,
        title: str,
        objective: str,
        repo: str,
        branch: str | None = None,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        """Cria uma nova sessão e registra no PostgreSQL.

        Nota: O PostgreSQL schema usa repository_id (FK), não repo (string).
        Para simplificar, usamos o repo name como session ID base e
        deixamos repository_id como NULL até que seja linkado via APIs.
        """
        session_id = _new_id()

        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Inserir sessão com user_id=NULL (será preenchido via API)
                cur.execute(
                    """
                    INSERT INTO sessions
                    (id, user_id, title, objective, status, progress_percentage, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id, title, objective, status, created_at
                    """,
                    (session_id, 1, title, objective, "active", 0),  # user_id=1 default
                )
                row = cur.fetchone()

        return {
            "id": row["id"],
            "title": row["title"],
            "objective": row["objective"],
            "status": row["status"],
            "progress_percentage": 0,
            "next_action": "create_branch_via_deploy_mcp",
        }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retorna a sessão completa."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, user_id, repository_id, title, objective, status,
                           progress_percentage, last_checkpoint_summary, created_at,
                           last_activity_at, completed_at
                    FROM sessions WHERE id = %s
                    """,
                    (session_id,),
                )
                return cur.fetchone()

    def list_sessions(
        self,
        status: str | None = None,
        repo: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Lista sessões com filtros opcionais."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT id, user_id, repository_id, title, objective, status, progress_percentage, created_at FROM sessions WHERE 1=1"
                params = []

                if status:
                    query += " AND status = %s"
                    params.append(status)

                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                return cur.fetchall() or []

    def update_session_progress(self, session_id: str, progress_percentage: int) -> None:
        """Atualiza progresso da sessão."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET progress_percentage = %s, last_activity_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (progress_percentage, session_id),
                )

    def set_session_branch(self, session_id: str, branch: str, base_branch: str | None = None) -> None:
        """Registra informações de branch (compatibilidade com session_tool.py)."""
        # Nota: PostgreSQL schema não tem colunas branch/base_branch
        # Armazenar em last_checkpoint_summary como fallback
        info = f"branch={branch}"
        if base_branch:
            info += f" base_branch={base_branch}"
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET last_checkpoint_summary = %s, last_activity_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (info, session_id),
                )

    def end_session(self, session_id: str, summary: str = "") -> None:
        """Marca sessão como completed."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET status = %s, completed_at = CURRENT_TIMESTAMP,
                        last_checkpoint_summary = %s, progress_percentage = 100
                    WHERE id = %s
                    """,
                    ("completed", summary, session_id),
                )

    # ────────────────────────────────────────────────────────────────────────── #
    # CHECKPOINT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def save_checkpoint(
        self,
        session_id: str,
        summary: str,
        context: dict[str, Any] | None = None,
    ) -> int:
        """Salva um checkpoint de progresso."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO checkpoints
                    (session_id, summary, context_snapshot, created_by_id, created_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (session_id, summary, json.dumps(context) if context else None, 1),
                )
                row = cur.fetchone()
                return row[0]

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """Lista checkpoints de uma sessão."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, session_id, summary, context_snapshot, created_at
                    FROM checkpoints WHERE session_id = %s ORDER BY created_at DESC
                    """,
                    (session_id,),
                )
                return cur.fetchall() or []

    # ────────────────────────────────────────────────────────────────────────── #
    # ARTIFACT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def add_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Registra um artefato (arquivo alterado, decisão, etc)."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO artifacts
                    (session_id, artifact_type, content, metadata, created_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (session_id, artifact_type, content, json.dumps(metadata) if metadata else None),
                )
                row = cur.fetchone()
                return row[0]

    def list_artifacts(
        self,
        session_id: str,
        artifact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista artefatos de uma sessão."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT id, session_id, artifact_type, content, metadata, created_at FROM artifacts WHERE session_id = %s"
                params = [session_id]

                if artifact_type:
                    query += " AND artifact_type = %s"
                    params.append(artifact_type)

                query += " ORDER BY created_at DESC"
                cur.execute(query, params)
                return cur.fetchall() or []

    # ────────────────────────────────────────────────────────────────────────── #
    # TASK OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def create_task(
        self,
        session_id: str,
        title: str,
        description: str = "",
        needs_human_decision: bool = False,
    ) -> int:
        """Cria uma nova task."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks
                    (session_id, title, description, status, needs_human_decision, created_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (session_id, title, description, "pending", needs_human_decision),
                )
                row = cur.fetchone()
                return row[0]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Retorna uma task específica."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, session_id, title, description, status,
                           needs_human_decision, progress_percentage, created_at, started_at, completed_at
                    FROM tasks WHERE id = %s
                    """,
                    (task_id,),
                )
                return cur.fetchone()

    def list_tasks(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista tasks de uma sessão."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT id, session_id, title, description, status, progress_percentage, created_at FROM tasks WHERE session_id = %s"
                params = [session_id]

                if status:
                    query += " AND status = %s"
                    params.append(status)

                query += " ORDER BY created_at ASC"
                cur.execute(query, params)
                return cur.fetchall() or []

    def start_task(self, task_id: int) -> None:
        """Marca task como in_progress."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tasks SET status = %s, started_at = CURRENT_TIMESTAMP WHERE id = %s",
                    ("in_progress", task_id),
                )

    def complete_task(self, task_id: int, result: str = "") -> None:
        """Marca task como completed."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tasks
                    SET status = %s, completed_at = CURRENT_TIMESTAMP, progress_percentage = 100
                    WHERE id = %s
                    """,
                    ("completed", task_id),
                )

    def fail_task(self, task_id: int, reason: str = "") -> None:
        """Marca task como failed."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tasks SET status = %s, completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                    ("failed", task_id),
                )

    # ────────────────────────────────────────────────────────────────────────── #
    # SUGGESTION OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def submit_suggestion(
        self,
        source_repo_id: int,
        target_repo_id: int,
        title: str,
        description: str = "",
        kind: str | None = None,
        priority: str | None = None,
    ) -> int:
        """Submete uma sugestão cross-repo."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO suggestions
                    (source_repository_id, target_repository_id, title, description, kind, priority, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (source_repo_id, target_repo_id, title, description, kind, priority, "pending"),
                )
                row = cur.fetchone()
                return row[0]

    def list_suggestions(
        self,
        target_repo_id: int | None = None,
        status: str | None = None,
        target_repo: str | None = None,
        source_repo: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Lista sugestões para um repositório."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT id, source_repository_id, target_repository_id, title, description, kind, priority, status, created_at FROM suggestions WHERE 1=1"
                params: list = []

                if target_repo_id is not None:
                    query += " AND target_repository_id = %s"
                    params.append(target_repo_id)
                if target_repo is not None:
                    query += " AND target_repository_id = %s"
                    params.append(target_repo)
                if source_repo is not None:
                    query += " AND source_repository_id = %s"
                    params.append(source_repo)
                if status:
                    query += " AND status = %s"
                    params.append(status)

                query += f" ORDER BY created_at DESC LIMIT {int(limit)}"
                cur.execute(query, params)
                return [dict(r) for r in (cur.fetchall() or [])]

    def count_pending_suggestions(self, target_repo: str) -> int:
        """Conta sugestões pendentes para um repositório."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM suggestions WHERE target_repository_id = %s AND status = 'pending'",
                    (target_repo,),
                )
                row = cur.fetchone()
                return row[0] if row else 0

    def update_suggestion_status(self, suggestion_id: int, status: str) -> None:
        """Atualiza status de uma sugestão."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE suggestions SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (status, suggestion_id),
                )

    # ────────────────────────────────────────────────────────────────────────── #
    # UTILITY METHODS (para compatibilidade com session_tool.py)
    # ────────────────────────────────────────────────────────────────────────── #

    def record_decision(
        self,
        actor_type: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        decision: str | None = None,
        rationale: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Registra uma decisão (audit trail via artifacts)."""
        content = {
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "decision": decision,
            "rationale": rationale,
        }
        if session_id:
            self.add_artifact(session_id, "decision", json.dumps(content))

    def get_resume_context(self, session_id: str) -> dict[str, Any]:
        """Retorna contexto completo para resumir sessão."""
        session = self.get_session(session_id)
        if not session:
            return {}

        return {
            "session": session,
            "recent_checkpoints": self.list_checkpoints(session_id)[:3],
            "recent_artifacts": self.list_artifacts(session_id)[:5],
            "open_tasks": self.list_tasks(session_id, status="in_progress"),
        }
