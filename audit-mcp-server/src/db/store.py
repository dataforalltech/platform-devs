"""AuditStore — persistência PostgreSQL para auditoria e compliance.

Tabela principal:
  audit_log — registro de cada auditoria com score, status, checklist
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from ..config.settings import AuditSettings

logger = logging.getLogger(__name__)


def _now() -> str:
    """Retorna ISO timestamp com timezone."""
    return datetime.now(timezone.utc).isoformat()


class AuditStore:
    """PostgreSQL thread-safe audit store com connection pool."""

    def __init__(self, settings: AuditSettings) -> None:
        self.settings = settings
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pg_min_conn,
            maxconn=settings.pg_max_conn,
            dsn=settings.pg_dsn,
        )
        logger.info(
            f"✅ AuditStore initialized with PostgreSQL pool ({settings.pg_min_conn}-{settings.pg_max_conn} connections)"
        )

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
            logger.info("AuditStore connection pool closed")

    def create_audit(
        self,
        service: str,
        repo: str,
        env: str,
        criticality: str,
        score: float,
        passed: bool,
        status: str,
        checklist: dict[str, Any],
    ) -> str:
        """Cria uma nova auditoria no PostgreSQL."""
        # Usar service como audit_id para simplificar (pode ser gerado via UUID se necessário)
        audit_id = f"audit_{service}_{env}"

        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log
                    (id, service, repo, env, criticality, score, passed, status, checklist, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (
                        audit_id,
                        service,
                        repo,
                        env,
                        criticality,
                        score,
                        passed,
                        status,
                        json.dumps(checklist),
                    ),
                )
                row = cur.fetchone()
                return row["id"] if row else audit_id

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        """Retorna uma auditoria específica."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM audit_log WHERE id = %s", (audit_id,))
                row = cur.fetchone()
                if row and isinstance(row.get("checklist"), str):
                    row["checklist"] = json.loads(row["checklist"])
                    row["passed"] = bool(row["passed"])
                return dict(row) if row else None

    def get_latest_audit(self, service: str, env: str) -> dict[str, Any] | None:
        """Retorna a auditoria mais recente de um serviço."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM audit_log
                    WHERE service = %s AND env = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (service, env),
                )
                row = cur.fetchone()
                if row and isinstance(row.get("checklist"), str):
                    row["checklist"] = json.loads(row["checklist"])
                    row["passed"] = bool(row["passed"])
                return dict(row) if row else None

    def list_audits(
        self,
        status: str | None = None,
        env: str | None = None,
        service: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lista auditorias com filtros opcionais."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT * FROM audit_log WHERE 1=1"
                params: list[Any] = []

                if status:
                    query += " AND status = %s"
                    params.append(status)
                if env:
                    query += " AND env = %s"
                    params.append(env)
                if service:
                    query += " AND service = %s"
                    params.append(service)

                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                rows = cur.fetchall()

                result = []
                for row in rows:
                    row_dict = dict(row)
                    if isinstance(row_dict.get("checklist"), str):
                        row_dict["checklist"] = json.loads(row_dict["checklist"])
                    if "passed" in row_dict:
                        row_dict["passed"] = bool(row_dict["passed"])
                    result.append(row_dict)
                return result

    def update_audit_status(self, audit_id: str, status: str, score: float, passed: bool) -> None:
        """Atualiza o status de uma auditoria."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE audit_log
                    SET status = %s, score = %s, passed = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, score, passed, audit_id),
                )

    def add_audit_item(
        self,
        audit_id: str,
        category: str,
        name: str,
        required: bool,
        passed: bool,
        details: str | None = None,
    ) -> None:
        """Adiciona um item de auditoria (armazenado em JSON na auditoria)."""
        # Nota: como a auditoria foi simplificada, armazenar checklist no JSON principal
        # Se houver tabela separada audit_items, usar aqui
        # Por enquanto, atualizar o checklist existente
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Buscar checklist atual
                cur.execute("SELECT checklist FROM audit_log WHERE id = %s", (audit_id,))
                row = cur.fetchone()
                if row:
                    checklist = json.loads(row["checklist"]) if isinstance(row["checklist"], str) else row["checklist"]
                    if not isinstance(checklist, dict):
                        checklist = {}
                    if "items" not in checklist:
                        checklist["items"] = []
                    checklist["items"].append({
                        "category": category,
                        "name": name,
                        "required": required,
                        "passed": passed,
                        "details": details,
                    })
                    cur.execute(
                        "UPDATE audit_log SET checklist = %s WHERE id = %s",
                        (json.dumps(checklist), audit_id),
                    )

    def get_audit_items(self, audit_id: str) -> list[dict[str, Any]]:
        """Retorna items de uma auditoria."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT checklist FROM audit_log WHERE id = %s", (audit_id,))
                row = cur.fetchone()
                if row and row.get("checklist"):
                    checklist = json.loads(row["checklist"]) if isinstance(row["checklist"], str) else row["checklist"]
                    return checklist.get("items", [])
                return []

    def add_approval(
        self,
        audit_id: str,
        approved_by: str,
        decision: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Registra uma aprovação de auditoria."""
        # Armazenar como parte do JSON da auditoria
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT checklist FROM audit_log WHERE id = %s", (audit_id,))
                row = cur.fetchone()
                if row:
                    checklist = json.loads(row["checklist"]) if isinstance(row["checklist"], str) else row["checklist"]
                    if not isinstance(checklist, dict):
                        checklist = {}
                    if "approvals" not in checklist:
                        checklist["approvals"] = []
                    checklist["approvals"].append({
                        "approved_by": approved_by,
                        "role": role,
                        "decision": decision,
                        "notes": notes,
                        "created_at": _now(),
                    })
                    cur.execute(
                        "UPDATE audit_log SET checklist = %s WHERE id = %s",
                        (json.dumps(checklist), audit_id),
                    )

    def get_approvals(self, audit_id: str) -> list[dict[str, Any]]:
        """Retorna aprovações de uma auditoria."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT checklist FROM audit_log WHERE id = %s", (audit_id,))
                row = cur.fetchone()
                if row and row.get("checklist"):
                    checklist = json.loads(row["checklist"]) if isinstance(row["checklist"], str) else row["checklist"]
                    return checklist.get("approvals", [])
                return []

    def set_service_criticality(self, service: str, criticality: str, updated_by: str) -> None:
        """Define criticidade de um serviço (armazenar em metadata)."""
        # Pode ser expandido para uma tabela separada se necessário
        pass

    def get_service_criticality(self, service: str) -> str:
        """Retorna criticidade padrão (medium)."""
        return "medium"
