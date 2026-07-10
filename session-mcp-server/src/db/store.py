"""SessionStore — persistência thread-safe para sessões de trabalho Claude Code.

Sete tabelas:
  sessions          — registro de cada sessão (repo dono é obrigatório)
  checkpoints       — snapshots do progresso salvos ao longo da sessão
  artifacts         — eventos relevantes (arquivos alterados, decisões, tool calls)
  tasks             — tarefas planejadas/executadas dentro da sessão
  session_services  — serviços auxiliares (registry do services-mcp) usados pela sessão
  suggestions       — fila cross-repo: repo X sugere algo para repo Y trabalhar
  decisions         — audit trail de decisões (quem decidiu o quê e por quê)

Backend: SQLite (embarcado, sem rede) exposto através de uma interface no estilo
PostgreSQL — placeholders ``%s``, ``_get_conn()`` como context manager e cursores que
retornam linhas do tipo dict (``RealDictCursor``). Isso mantém a camada de tools e os
testes 100% hermeticos: nenhuma conexão de rede é aberta, nada bloqueia.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

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
    """Gera um nome único para a sessão no formato <adjetivo>-<personagem>."""
    adjectives = ["ancient", "blazing", "bold", "calm", "cosmic", "clever", "daring", "divine"]
    names = ["zeus", "odin", "athena", "batman", "marvel", "goku", "loki", "thor"]
    return f"{random.choice(adjectives)}-{random.choice(names)}"  # noqa: S311


def _now() -> str:
    """Retorna ISO timestamp com timezone."""
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    """Gera um session id no formato sess_<8 hex>."""
    return f"sess_{uuid.uuid4().hex[:8]}"


class _CursorAdapter:
    """Adapta um cursor sqlite3 para a interface usada pela camada de tools/testes.

    - Traduz placeholders ``%s`` (estilo psycopg2) para ``?`` (estilo sqlite3).
    - ``fetchone``/``fetchall`` retornam ``dict`` (equivalente ao ``RealDictCursor``)
      quando o cursor foi criado como dict cursor; caso contrário retornam tuplas
      (permitindo acesso por índice, ex: ``cur.fetchone()[0]``).
    """

    def __init__(self, cursor: sqlite3.Cursor, *, as_dict: bool) -> None:
        self._cur = cursor
        self._as_dict = as_dict

    @staticmethod
    def _translate(query: str) -> str:
        return query.replace("%s", "?")

    def execute(self, query: str, params: Any = ()) -> _CursorAdapter:
        self._cur.execute(self._translate(query), tuple(params) if params else ())
        return self

    def _row(self, row: sqlite3.Row | None) -> Any:
        if row is None:
            return None
        if self._as_dict:
            return dict(row)
        return tuple(row)

    def fetchone(self) -> Any:
        return self._row(self._cur.fetchone())

    def fetchall(self) -> list[Any]:
        return [self._row(r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self) -> int | None:
        return self._cur.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def close(self) -> None:
        self._cur.close()

    def __enter__(self) -> _CursorAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self._cur.close()


class _ConnAdapter:
    """Adapta uma conexão sqlite3 para a interface no estilo psycopg2.

    Expõe ``cursor(cursor_factory=...)`` e ``commit``/``rollback``. Quando o
    ``cursor_factory`` é um dict cursor (ex: ``RealDictCursor``), as linhas voltam
    como ``dict``; caso contrário voltam como tuplas.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self, cursor_factory: Any = None) -> _CursorAdapter:
        as_dict = cursor_factory is not None
        return _CursorAdapter(self._conn.cursor(), as_dict=as_dict)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


class SessionStore:
    """Session store thread-safe (SQLite embarcado, interface estilo PostgreSQL)."""

    def __init__(self, settings: SessionSettings) -> None:
        self.settings = settings
        # SQLite em memória compartilhado entre threads. check_same_thread=False +
        # lock explícito garantem uso seguro sem abrir nenhuma conexão de rede.
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_db()
        logger.info("✅ SessionStore initialized (SQLite in-memory, hermetic)")

    # ────────────────────────────────────────────────────────────────────────── #
    # Internals
    # ────────────────────────────────────────────────────────────────────────── #

    @contextmanager
    def _get_conn(self):
        """Context manager para obter a conexão (estilo psycopg2 pool)."""
        self._lock.acquire()
        adapter = _ConnAdapter(self._conn)
        try:
            yield adapter
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._lock.release()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id               TEXT PRIMARY KEY,
                    name             TEXT,
                    title            TEXT NOT NULL,
                    objective        TEXT NOT NULL,
                    repo             TEXT,
                    branch           TEXT,
                    base_branch      TEXT,
                    status           TEXT NOT NULL DEFAULT 'active',
                    progress         TEXT,
                    started_at       TEXT NOT NULL,
                    last_updated_at  TEXT NOT NULL,
                    ended_at         TEXT
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT NOT NULL,
                    summary      TEXT NOT NULL,
                    context_json TEXT,
                    created_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    type        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id            TEXT NOT NULL,
                    title                 TEXT NOT NULL,
                    description           TEXT,
                    status                TEXT NOT NULL DEFAULT 'pending',
                    sort_order            INTEGER NOT NULL DEFAULT 0,
                    result                TEXT,
                    commit_sha            TEXT,
                    commit_message        TEXT,
                    needs_human_decision  INTEGER NOT NULL DEFAULT 0,
                    decision              TEXT,
                    decided_at            TEXT,
                    decision_notes        TEXT,
                    created_at            TEXT NOT NULL,
                    started_at            TEXT,
                    completed_at          TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_session_status
                    ON tasks(session_id, status);

                CREATE TABLE IF NOT EXISTS session_services (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    service     TEXT NOT NULL,
                    role        TEXT,
                    notes       TEXT,
                    added_at    TEXT NOT NULL,
                    UNIQUE(session_id, service)
                );

                CREATE TABLE IF NOT EXISTS suggestions (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_repo         TEXT NOT NULL,
                    source_session_id   TEXT,
                    target_repo         TEXT NOT NULL,
                    title               TEXT NOT NULL,
                    description         TEXT,
                    kind                TEXT,
                    priority            TEXT,
                    status              TEXT NOT NULL DEFAULT 'pending',
                    response_reason     TEXT,
                    accepted_session_id TEXT,
                    accepted_task_id    INTEGER,
                    superseded_by       INTEGER,
                    created_at          TEXT NOT NULL,
                    responded_at        TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_suggestions_target_status
                    ON suggestions(target_repo, status);

                CREATE TABLE IF NOT EXISTS decisions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_type    TEXT NOT NULL,
                    actor_id      TEXT NOT NULL,
                    action        TEXT NOT NULL,
                    target_type   TEXT NOT NULL,
                    target_id     TEXT NOT NULL,
                    decision      TEXT,
                    rationale     TEXT,
                    context_json  TEXT,
                    session_id    TEXT,
                    created_at    TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_decisions_target
                    ON decisions(target_type, target_id);
                CREATE INDEX IF NOT EXISTS idx_decisions_actor
                    ON decisions(actor_type, actor_id);
                CREATE INDEX IF NOT EXISTS idx_decisions_session
                    ON decisions(session_id);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        """Fecha a conexão."""
        with self._lock:
            self._conn.close()
            logger.info("SessionStore connection closed")

    # ── helpers de leitura ────────────────────────────────────────────────── #

    def _exists_session(self, session_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row is not None

    def _row_to_session(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        cp = self._conn.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (d["id"],),
        ).fetchone()
        d["last_checkpoint"] = dict(cp) if cp else None
        d["artifacts_count"] = self._conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE session_id = ?", (d["id"],)
        ).fetchone()[0]
        d["tasks_summary"] = self._tasks_summary(d["id"])
        d["service_dependencies"] = self._list_service_deps(d["id"])
        return d

    def _list_service_deps(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM session_services WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _tasks_summary(self, session_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE session_id = ? GROUP BY status",
            (session_id,),
        ).fetchall()
        summary: dict[str, int] = {s: 0 for s in TASK_STATUSES}
        summary["total"] = 0
        for r in rows:
            summary[r["status"]] = r["n"]
            summary["total"] += r["n"]
        return summary

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

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
        """Cria uma sessão. `repo` (owner repo) é obrigatório."""
        session_id = _new_id()
        name = _generate_name()
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO sessions (id, name, title, objective, repo, branch,
                   base_branch, status, started_at, last_updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (session_id, name, title, objective, repo, branch, base_branch, now, now),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return self._row_to_session(row)

    def set_session_branch(self, session_id: str, branch: str, base_branch: str | None = None) -> None:
        """Registra a branch da sessão (e sua base)."""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET branch = ?, base_branch = ?, last_updated_at = ? WHERE id = ?",
                (branch, base_branch, _now(), session_id),
            )
            self._conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retorna a sessão completa (com último checkpoint, contagens e dependências)."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            return self._row_to_session(row)

    def list_sessions(
        self,
        status: str | None = None,
        repo: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Lista sessões com filtros opcionais."""
        with self._lock:
            query = "SELECT * FROM sessions WHERE 1=1"
            params: list[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if repo:
                query += " AND repo LIKE ?"
                params.append(f"%{repo}%")
            query += " ORDER BY last_updated_at DESC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
            return [self._row_to_session(r) for r in rows]

    def update_session(
        self,
        session_id: str,
        status: str | None = None,
        progress: str | None = None,
    ) -> dict[str, Any] | None:
        """Atualiza status e/ou progresso. Retorna a sessão ou None se não existe."""
        now = _now()
        updates = ["last_updated_at = ?"]
        params: list[Any] = [now]
        if status:
            updates.append("status = ?")
            params.append(status)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        params.append(session_id)
        with self._lock:
            if not self._exists_session(session_id):
                return None
            self._conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return self._row_to_session(row)

    def end_session(
        self,
        session_id: str,
        summary: str = "",
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Encerra a sessão.

        Retorna:
          - dict (sessão) em caso de sucesso;
          - list[dict] com tasks abertas se houver pendências (sessão NÃO encerrada);
          - None se a sessão não existe.
        """
        now = _now()
        with self._lock:
            if not self._exists_session(session_id):
                return None
            placeholders = ",".join("?" for _ in TASK_OPEN_STATUSES)
            open_rows = self._conn.execute(
                f"SELECT * FROM tasks WHERE session_id = ? AND status IN ({placeholders}) "
                "ORDER BY sort_order ASC, id ASC",
                (session_id, *TASK_OPEN_STATUSES),
            ).fetchall()
            if open_rows:
                return [self._row_to_task(r) for r in open_rows]
            self._conn.execute(
                "UPDATE sessions SET status = 'completed', ended_at = ?, last_updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )
            if summary:
                self._conn.execute(
                    "INSERT INTO checkpoints (session_id, summary, created_at) VALUES (?, ?, ?)",
                    (session_id, f"[FINAL] {summary}", now),
                )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return self._row_to_session(row)

    # ────────────────────────────────────────────────────────────────────────── #
    # CHECKPOINT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def save_checkpoint(
        self,
        session_id: str,
        summary: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Salva um checkpoint de progresso."""
        now = _now()
        context_json = json.dumps(context, ensure_ascii=False) if context else None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO checkpoints (session_id, summary, context_json, created_at) VALUES (?, ?, ?, ?)",
                (session_id, summary, context_json, now),
            )
            self._conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (now, session_id))
            checkpoint_id = cur.lastrowid
            self._conn.commit()
        return {
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "summary": summary,
            "saved_at": now,
        }

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """Lista checkpoints de uma sessão (mais recente primeiro)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY id DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ────────────────────────────────────────────────────────────────────────── #
    # ARTIFACT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def add_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: str,
    ) -> dict[str, Any]:
        """Registra um artefato (arquivo alterado, decisão, etc)."""
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO artifacts (session_id, type, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, artifact_type, content, now),
            )
            self._conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (now, session_id))
            artifact_id = cur.lastrowid
            self._conn.commit()
        return {
            "artifact_id": artifact_id,
            "session_id": session_id,
            "type": artifact_type,
            "content": content,
            "created_at": now,
        }

    def list_artifacts(
        self,
        session_id: str,
        artifact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista artefatos de uma sessão."""
        with self._lock:
            query = "SELECT * FROM artifacts WHERE session_id = ?"
            params: list[Any] = [session_id]
            if artifact_type:
                query += " AND type = ?"
                params.append(artifact_type)
            query += " ORDER BY id DESC"
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ────────────────────────────────────────────────────────────────────────── #
    # TASK OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def _next_sort_order(self, session_id: str) -> int:
        return self._conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]

    def create_task(
        self,
        session_id: str,
        title: str,
        description: str | None = None,
        needs_human_decision: bool = False,
    ) -> dict[str, Any] | None:
        """Cria uma nova task. Retorna None se a sessão não existe."""
        now = _now()
        with self._lock:
            if not self._exists_session(session_id):
                return None
            next_order = self._next_sort_order(session_id)
            cur = self._conn.execute(
                """INSERT INTO tasks (session_id, title, description, status, sort_order,
                   needs_human_decision, created_at)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
                (
                    session_id,
                    title,
                    description,
                    next_order,
                    1 if needs_human_decision else 0,
                    now,
                ),
            )
            self._conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
            return self._row_to_task(row)

    def create_tasks(
        self,
        session_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Cria várias tasks preservando a ordem. Retorna None se a sessão não existe."""
        if not tasks:
            return []
        now = _now()
        created: list[dict[str, Any]] = []
        with self._lock:
            if not self._exists_session(session_id):
                return None
            next_order = self._next_sort_order(session_id)
            for offset, item in enumerate(tasks):
                cur = self._conn.execute(
                    """INSERT INTO tasks (session_id, title, description, status, sort_order,
                       needs_human_decision, created_at)
                       VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
                    (
                        session_id,
                        item["title"],
                        item.get("description"),
                        next_order + offset,
                        1 if item.get("needs_human_decision") else 0,
                        now,
                    ),
                )
                row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
                created.append(self._row_to_task(row))
            self._conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()
        return created

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Retorna uma task específica."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None

    def list_tasks(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """Lista tasks de uma sessão. Retorna None se a sessão não existe."""
        with self._lock:
            if not self._exists_session(session_id):
                return None
            query = "SELECT * FROM tasks WHERE session_id = ?"
            params: list[Any] = [session_id]
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY sort_order ASC, id ASC"
            rows = self._conn.execute(query, params).fetchall()
            return [self._row_to_task(r) for r in rows]

    def _transition_task(
        self,
        task_id: int,
        *,
        new_status: str,
        allowed_from: tuple[str, ...],
        result: str | None = None,
        commit_sha: str | None = None,
        commit_message: str | None = None,
        set_started_at: bool = False,
        set_completed_at: bool = False,
    ) -> dict[str, Any] | str | None:
        """Aplica transição de estado. Retorna a task atualizada, None se não existe,
        ou string com o estado atual quando a transição não é permitida."""
        now = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            if row["status"] not in allowed_from:
                return row["status"]
            updates = ["status = ?"]
            params: list[Any] = [new_status]
            if set_started_at and not row["started_at"]:
                updates.append("started_at = ?")
                params.append(now)
            if set_completed_at:
                updates.append("completed_at = ?")
                params.append(now)
            if result is not None:
                updates.append("result = ?")
                params.append(result)
            if commit_sha is not None:
                updates.append("commit_sha = ?")
                params.append(commit_sha)
            if commit_message is not None:
                updates.append("commit_message = ?")
                params.append(commit_message)
            params.append(task_id)
            self._conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            self._conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, row["session_id"]),
            )
            self._conn.commit()
            updated = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(updated)

    def start_task(self, task_id: int) -> dict[str, Any] | str | None:
        """Marca task como in_progress (a partir de pending)."""
        return self._transition_task(
            task_id,
            new_status="in_progress",
            allowed_from=("pending",),
            set_started_at=True,
        )

    def complete_task(
        self,
        task_id: int,
        result: str | None = None,
        commit_sha: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Marca task como completed registrando o commit."""
        return self._transition_task(
            task_id,
            new_status="completed",
            allowed_from=("pending", "in_progress"),
            result=result,
            commit_sha=commit_sha,
            commit_message=commit_message,
            set_started_at=True,
            set_completed_at=True,
        )

    def fail_task(self, task_id: int, reason: str) -> dict[str, Any] | str | None:
        """Marca task como failed."""
        return self._transition_task(
            task_id,
            new_status="failed",
            allowed_from=("pending", "in_progress"),
            result=reason,
            set_completed_at=True,
        )

    def cancel_task(self, task_id: int, reason: str | None = None) -> dict[str, Any] | str | None:
        """Cancela task (de pending ou in_progress)."""
        return self._transition_task(
            task_id,
            new_status="cancelled",
            allowed_from=("pending", "in_progress"),
            result=reason,
            set_completed_at=True,
        )

    def approve_task(
        self,
        task_id: int,
        decision: str,
        notes: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Registra decisão humana sobre uma task pendente.

        decision='go'    → marca decision='go'; a task fica pending mas liberada.
        decision='no_go' → cancela a task usando notes como reason.
        """
        now = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            if row["status"] != "pending":
                return row["status"]
            if decision == "go":
                self._conn.execute(
                    "UPDATE tasks SET decision='go', decided_at=?, decision_notes=? WHERE id=?",
                    (now, notes, task_id),
                )
            elif decision == "no_go":
                self._conn.execute(
                    """UPDATE tasks SET decision='no_go', decided_at=?, decision_notes=?,
                       status='cancelled', completed_at=?, result=? WHERE id=?""",
                    (now, notes, now, notes or "no_go (human decision)", task_id),
                )
            else:
                raise ValueError(f"decision inválida: '{decision}'")
            self._conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, row["session_id"]),
            )
            self._conn.commit()
            updated = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(updated)

    # ────────────────────────────────────────────────────────────────────────── #
    # SERVICE DEPENDENCY OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def add_service_dependency(
        self,
        session_id: str,
        service: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Vincula um serviço auxiliar à sessão.

        Retorna o registro criado, 'duplicate' se já vinculado, ou None se a sessão
        não existe.
        """
        now = _now()
        with self._lock:
            if not self._exists_session(session_id):
                return None
            existing = self._conn.execute(
                "SELECT 1 FROM session_services WHERE session_id = ? AND service = ?",
                (session_id, service),
            ).fetchone()
            if existing:
                return "duplicate"
            cur = self._conn.execute(
                "INSERT INTO session_services (session_id, service, role, notes, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, service, role, notes, now),
            )
            self._conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM session_services WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_service_dependencies(self, session_id: str) -> list[dict[str, Any]] | None:
        """Lista os serviços auxiliares. Retorna None se a sessão não existe."""
        with self._lock:
            if not self._exists_session(session_id):
                return None
            return self._list_service_deps(session_id)

    def remove_service_dependency(self, session_id: str, service: str) -> bool | None:
        """Remove um vínculo. Retorna True se removeu, False se não existia,
        None se a sessão não existe."""
        now = _now()
        with self._lock:
            if not self._exists_session(session_id):
                return None
            cur = self._conn.execute(
                "DELETE FROM session_services WHERE session_id = ? AND service = ?",
                (session_id, service),
            )
            if cur.rowcount == 0:
                self._conn.commit()
                return False
            self._conn.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()
            return True

    # ────────────────────────────────────────────────────────────────────────── #
    # SUGGESTION OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    def create_suggestion(
        self,
        *,
        source_repo: str,
        target_repo: str,
        title: str,
        description: str | None = None,
        kind: str | None = None,
        priority: str | None = None,
        source_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Submete uma sugestão cross-repo."""
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO suggestions
                   (source_repo, source_session_id, target_repo, title, description,
                    kind, priority, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    source_repo,
                    source_session_id,
                    target_repo,
                    title,
                    description,
                    kind,
                    priority,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM suggestions WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def get_suggestion(self, suggestion_id: int) -> dict[str, Any] | None:
        """Retorna uma sugestão pelo ID."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            return dict(row) if row else None

    def list_suggestions(
        self,
        target_repo: str | None = None,
        source_repo: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Lista sugestões com filtros opcionais."""
        with self._lock:
            query = "SELECT * FROM suggestions WHERE 1=1"
            params: list[Any] = []
            if target_repo:
                query += " AND target_repo = ?"
                params.append(target_repo)
            if source_repo:
                query += " AND source_repo = ?"
                params.append(source_repo)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def count_pending_suggestions(self, target_repo: str) -> int:
        """Conta sugestões pendentes para um repositório."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM suggestions WHERE target_repo = ? AND status = 'pending'",
                (target_repo,),
            ).fetchone()
            return row["n"] if row else 0

    def transition_suggestion(
        self,
        suggestion_id: int,
        *,
        new_status: str,
        allowed_from: tuple[str, ...] = ("pending",),
        response_reason: str | None = None,
        accepted_session_id: str | None = None,
        accepted_task_id: int | None = None,
        superseded_by: int | None = None,
    ) -> dict[str, Any] | str | None:
        """Aplica transição. Retorna registro atualizado, None se não existe,
        ou string com status atual se a transição é inválida."""
        now = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            if not row:
                return None
            if row["status"] not in allowed_from:
                return row["status"]
            updates = ["status = ?", "responded_at = ?"]
            params: list[Any] = [new_status, now]
            if response_reason is not None:
                updates.append("response_reason = ?")
                params.append(response_reason)
            if accepted_session_id is not None:
                updates.append("accepted_session_id = ?")
                params.append(accepted_session_id)
            if accepted_task_id is not None:
                updates.append("accepted_task_id = ?")
                params.append(accepted_task_id)
            if superseded_by is not None:
                updates.append("superseded_by = ?")
                params.append(superseded_by)
            params.append(suggestion_id)
            self._conn.execute(f"UPDATE suggestions SET {', '.join(updates)} WHERE id = ?", params)
            self._conn.commit()
            updated = self._conn.execute(
                "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            return dict(updated)

    # ────────────────────────────────────────────────────────────────────────── #
    # DECISION OPERATIONS (audit trail)
    # ────────────────────────────────────────────────────────────────────────── #

    def record_decision(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        decision: str | None = None,
        rationale: str | None = None,
        context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma decisão no audit trail."""
        now = _now()
        ctx_json = json.dumps(context, ensure_ascii=False) if context else None
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO decisions (actor_type, actor_id, action, target_type,
                   target_id, decision, rationale, context_json, session_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    actor_type,
                    actor_id,
                    action,
                    target_type,
                    target_id,
                    decision,
                    rationale,
                    ctx_json,
                    session_id,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM decisions WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def list_decisions(
        self,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Lista o audit trail com filtros opcionais."""
        with self._lock:
            query = "SELECT * FROM decisions WHERE 1=1"
            params: list[Any] = []
            for col, val in (
                ("target_type", target_type),
                ("target_id", target_id),
                ("actor_type", actor_type),
                ("actor_id", actor_id),
                ("action", action),
                ("session_id", session_id),
            ):
                if val is not None:
                    query += f" AND {col} = ?"
                    params.append(val)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        """Retorna uma decisão pelo ID."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
            return dict(row) if row else None

    # ────────────────────────────────────────────────────────────────────────── #
    # RESUME
    # ────────────────────────────────────────────────────────────────────────── #

    def get_resume_context(self, session_id: str) -> dict[str, Any] | None:
        """Retorna o contexto completo para retomar uma sessão."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            session = dict(row)

            cps = self._conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT 5",
                (session_id,),
            ).fetchall()
            checkpoints = [dict(c) for c in cps]

            arts = self._conn.execute(
                "SELECT * FROM artifacts WHERE session_id = ? ORDER BY id DESC LIMIT 20",
                (session_id,),
            ).fetchall()
            artifacts = [dict(a) for a in arts]

            placeholders = ",".join("?" for _ in TASK_OPEN_STATUSES)
            open_rows = self._conn.execute(
                f"SELECT * FROM tasks WHERE session_id = ? AND status IN ({placeholders}) "
                "ORDER BY sort_order ASC, id ASC",
                (session_id, *TASK_OPEN_STATUSES),
            ).fetchall()
            open_tasks = [dict(t) for t in open_rows]
            tasks_summary = self._tasks_summary(session_id)

            service_deps = self._list_service_deps(session_id)

            pending_suggestions: list[dict[str, Any]] = []
            pending_count = 0
            if session.get("repo"):
                pending_count = self._conn.execute(
                    "SELECT COUNT(*) FROM suggestions WHERE target_repo = ? AND status = 'pending'",
                    (session["repo"],),
                ).fetchone()[0]
                pending_rows = self._conn.execute(
                    "SELECT * FROM suggestions WHERE target_repo = ? AND status = 'pending' "
                    "ORDER BY created_at DESC, id DESC LIMIT 5",
                    (session["repo"],),
                ).fetchall()
                pending_suggestions = [dict(r) for r in pending_rows]

            warnings: list[str] = []
            if not session.get("repo"):
                warnings.append(
                    "REPO_MISSING: sessão sem repositório dono. Use update_session "
                    "para definir o repo antes de continuar — serviços auxiliares "
                    "devem ser registrados via add_service_dependency consultando "
                    "o services-mcp."
                )

            last_summary = checkpoints[0]["summary"] if checkpoints else "nenhum checkpoint salvo"
            name_part = f" [{session.get('name')}]" if session.get("name") else ""
            tasks_part = ""
            if open_tasks:
                titles = ", ".join(f"#{t['id']} {t['title']}" for t in open_tasks[:5])
                more = f" (+{len(open_tasks) - 5})" if len(open_tasks) > 5 else ""
                tasks_part = f" Tarefas abertas: {titles}{more}."
            services_part = ""
            if service_deps:
                names = ", ".join(s["service"] for s in service_deps[:5])
                more = f" (+{len(service_deps) - 5})" if len(service_deps) > 5 else ""
                services_part = f" Serviços auxiliares: {names}{more}."
            suggestions_part = ""
            if pending_count:
                titles = ", ".join(f"#{s['id']} {s['title']}" for s in pending_suggestions[:3])
                more = f" (+{pending_count - 3})" if pending_count > 3 else ""
                suggestions_part = f" Sugestões pendentes: {titles}{more}."
            warnings_part = ""
            if warnings:
                warnings_part = " ⚠ " + " ⚠ ".join(warnings)
            resume_hint = (
                f"Retomando sessão{name_part} '{session['title']}'. "
                f"Objetivo: {session['objective']}. "
                f"Repo: {session.get('repo') or 'não definido'}, "
                f"branch: {session.get('branch') or 'não definida'}. "
                f"Progresso atual: {session.get('progress') or 'não registrado'}. "
                f"Último checkpoint: {last_summary}."
                f"{tasks_part}"
                f"{services_part}"
                f"{suggestions_part}"
                f"{warnings_part}"
            )

            return {
                "session": session,
                "checkpoints": checkpoints,
                "recent_artifacts": artifacts,
                "open_tasks": open_tasks,
                "tasks_summary": tasks_summary,
                "service_dependencies": service_deps,
                "pending_suggestions": {
                    "count": pending_count,
                    "items": pending_suggestions,
                },
                "warnings": warnings,
                "resume_hint": resume_hint,
            }
