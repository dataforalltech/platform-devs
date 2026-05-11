"""DocsStore — persistência PostgreSQL thread-safe para documentação de repositórios.

Tabelas principais:
  documents — registro de documentos (READMEs, ADRs, etc.)
  audits    — auditorias de qualidade de documentação
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

from ..config.settings import DocsSettings

logger = logging.getLogger(__name__)


def _now() -> str:
    """Retorna ISO timestamp com timezone."""
    return datetime.now(timezone.utc).isoformat()


class DocsStore:
    """PostgreSQL thread-safe document store com connection pool."""

    def __init__(self, settings: DocsSettings) -> None:
        self.settings = settings
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pg_min_conn,
            maxconn=settings.pg_max_conn,
            dsn=settings.pg_dsn,
        )
        logger.info(f"✅ DocsStore initialized with PostgreSQL pool ({settings.pg_min_conn}-{settings.pg_max_conn} connections)")

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
            logger.info("DocsStore connection pool closed")

    # ────────────────────────────────────────────────────────────────────────── #
    # AUDIT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def save_audit(
        self,
        repo_path: str,
        score: int,
        grade: str,
        summary: dict,
        details: dict,
        duration_ms: int | None = None,
    ) -> int:
        """Salva resultado de auditoria de documentação."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (repo_path, doc_type, title, content, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (
                        repo_path,
                        "audit",
                        f"Audit: {grade}",
                        json.dumps({
                            "score": score,
                            "grade": grade,
                            "summary": summary,
                            "details": details,
                            "duration_ms": duration_ms,
                        }),
                        "completed",
                    ),
                )
                row = cur.fetchone()
                return row[0]

    def list_audits(
        self,
        repo_path: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Lista auditorias de documentação."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = "SELECT id, repo_path, title, content, created_at FROM documents WHERE doc_type = %s"
                params = ["audit"]

                if repo_path:
                    query += " AND repo_path = %s"
                    params.append(repo_path)

                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                rows = cur.fetchall() or []
                result = []
                for row in rows:
                    content = json.loads(row["content"]) if row["content"] else {}
                    result.append({
                        "id": row["id"],
                        "repo_path": row["repo_path"],
                        "title": row["title"],
                        "score": content.get("score"),
                        "grade": content.get("grade"),
                        "summary": content.get("summary", {}),
                        "details": content.get("details", {}),
                        "created_at": row["created_at"],
                    })
                return result

    # ────────────────────────────────────────────────────────────────────────── #
    # DOCUMENT INDEX OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def upsert_doc_index(
        self,
        repo_path: str,
        file_path: str,
        doc_type: str | None,
        title: str | None,
        word_count: int,
        last_modified: str | None,
        content_hash: str | None,
    ) -> None:
        """Insere ou atualiza documento no índice."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                # Tenta atualizar primeiro
                cur.execute(
                    """
                    UPDATE documents
                    SET doc_type = %s, title = %s, content = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE repo_path = %s AND title = %s
                    """,
                    (
                        doc_type,
                        file_path,
                        json.dumps({
                            "word_count": word_count,
                            "last_modified": last_modified,
                            "content_hash": content_hash,
                            "file_path": file_path,
                        }),
                        repo_path,
                        file_path,
                    ),
                )

                # Se nenhuma linha foi atualizada, insere
                if cur.rowcount == 0:
                    cur.execute(
                        """
                        INSERT INTO documents
                        (repo_path, doc_type, title, content, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (
                            repo_path,
                            doc_type,
                            file_path,
                            json.dumps({
                                "word_count": word_count,
                                "last_modified": last_modified,
                                "content_hash": content_hash,
                                "file_path": file_path,
                            }),
                            "indexed",
                        ),
                    )

    def search_index(self, repo_path: str, query: str) -> list[dict[str, Any]]:
        """Busca documentos no índice."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, repo_path, doc_type, title, content, created_at
                    FROM documents
                    WHERE repo_path = %s AND title ILIKE %s
                    ORDER BY title
                    """,
                    (repo_path, f"%{query}%"),
                )
                rows = cur.fetchall() or []
                result = []
                for row in rows:
                    content = json.loads(row["content"]) if row["content"] else {}
                    result.append({
                        "id": row["id"],
                        "repo_path": row["repo_path"],
                        "doc_type": row["doc_type"],
                        "title": row["title"],
                        "word_count": content.get("word_count", 0),
                        "last_modified": content.get("last_modified"),
                        "content_hash": content.get("content_hash"),
                        "file_path": content.get("file_path"),
                        "created_at": row["created_at"],
                    })
                return result

    def get_index(self, repo_path: str) -> list[dict[str, Any]]:
        """Retorna índice completo de um repositório."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, repo_path, doc_type, title, content, created_at
                    FROM documents
                    WHERE repo_path = %s AND doc_type != %s
                    ORDER BY title
                    """,
                    (repo_path, "audit"),
                )
                rows = cur.fetchall() or []
                result = []
                for row in rows:
                    content = json.loads(row["content"]) if row["content"] else {}
                    result.append({
                        "id": row["id"],
                        "repo_path": row["repo_path"],
                        "doc_type": row["doc_type"],
                        "title": row["title"],
                        "word_count": content.get("word_count", 0),
                        "last_modified": content.get("last_modified"),
                        "content_hash": content.get("content_hash"),
                        "file_path": content.get("file_path"),
                        "created_at": row["created_at"],
                    })
                return result
