"""SessionStore — persistência SQLite thread-safe para sessões de trabalho Claude Code.

Sete tabelas:
  sessions          — registro de cada sessão (repo dono é obrigatório)
  checkpoints       — snapshots do progresso salvos ao longo da sessão
  artifacts         — eventos relevantes (arquivos alterados, decisões, tool calls)
  tasks             — tarefas planejadas/executadas dentro da sessão
  session_services  — serviços auxiliares (registry do services-mcp) usados pela sessão
  suggestions       — fila cross-repo: repo X sugere algo para repo Y trabalhar
  decisions         — audit trail de decisões (quem decidiu o quê e por quê)
"""

from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TASK_STATUSES = ("pending", "in_progress", "completed", "failed", "cancelled")
TASK_OPEN_STATUSES = ("pending", "in_progress")
TASK_TERMINAL_STATUSES = ("completed", "failed", "cancelled")

SUGGESTION_STATUSES = ("pending", "accepted", "rejected", "deferred", "superseded")
SUGGESTION_KINDS = ("improvement", "correction", "addition", "question", "other")
SUGGESTION_PRIORITIES = ("low", "medium", "high", "critical")

ACTOR_TYPES = ("human", "agent", "system")


# ── Geração de nomes famosos ──────────────────────────────────────────────── #

_ADJECTIVES = [
    "ancient", "blazing", "bold", "calm", "chaotic", "clever", "cosmic",
    "cursed", "dark", "daring", "divine", "epic", "eternal", "fierce",
    "focused", "forgotten", "frozen", "furious", "glorious", "golden",
    "hungry", "infinite", "inspired", "legendary", "lucid", "mighty",
    "nimble", "patient", "phantom", "precise", "radiant", "resilient",
    "sacred", "shadow", "sharp", "silent", "solar", "steadfast", "swift",
    "tenacious", "thunder", "vivid", "wild", "wise", "zealous",
]

_FAMOUS = [
    # ── Mitologia ──────────────────────────────────────────────────────────── #
    "zeus", "odin", "athena", "poseidon", "hades", "hermes", "apollo",
    "artemis", "ares", "medusa", "achilles", "odysseus", "hercules",
    "anubis", "osiris", "ra", "fenrir", "freyja", "loki", "thor",
    "baldur", "tyr", "shiva", "vishnu", "kali", "izanagi",
    # ── Super-heróis ───────────────────────────────────────────────────────── #
    "batman", "spiderman", "wolverine", "ironman", "hulk", "cyclops",
    "storm", "daredevil", "deadpool", "black-panther", "wonder-woman",
    "flash", "aquaman", "nightcrawler", "captain-america", "doctor-strange",
    "hawkeye", "ant-man", "silver-surfer", "ghost-rider",
    # ── Vilões ─────────────────────────────────────────────────────────────── #
    "joker", "thanos", "magneto", "darkseid", "doom", "apocalypse",
    "red-skull", "carnage", "bane", "green-goblin", "galactus", "ultron",
    "venom", "sinestro", "lex-luthor", "brainiac", "mephisto",
    # ── Anime ──────────────────────────────────────────────────────────────── #
    "naruto", "sasuke", "goku", "vegeta", "luffy", "zoro", "ichigo",
    "edward", "eren", "levi", "spike", "tanjiro", "gintoki", "jotaro",
    "dio", "giorno", "guts", "griffith", "light-yagami", "ryuk",
    "alphonse", "mikasa", "saitama", "aizawa", "todoroki", "itachi",
    # ── Desenhos & Cartoons ────────────────────────────────────────────────── #
    "bugs-bunny", "daffy", "homer", "bart", "shaggy", "he-man", "skeletor",
    "optimus", "megatron", "spongebob", "courage", "finn", "jake", "rick",
    "morty", "stewie", "peter-griffin", "bojack", "bender", "zim",
    "avatar-aang", "katara", "zuko", "samurai-jack",
    # ── Games ──────────────────────────────────────────────────────────────── #
    "mario", "link", "ganon", "samus", "kirby", "sonic", "megaman",
    "cloud", "sephiroth", "kratos", "dante", "geralt", "master-chief",
    "solid-snake", "big-boss", "shovel-knight", "pac-man", "donkey-kong",
]


def _generate_name() -> str:
    """Gera um nome no formato <adjetivo>-<personagem>."""
    return f"{random.choice(_ADJECTIVES)}-{random.choice(_FAMOUS)}"  # noqa: S311


class SessionStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

        # Initialize PostgreSQL sync layer (Phase 2 integration)
        self.postgres_sync = None
        postgres_enabled = os.getenv("POSTGRES_SYNC_ENABLED", "true").lower() == "true"
        if postgres_enabled:
            try:
                from postgres_sync import SessionPostgresSync

                postgres_config = {
                    "dbname": os.getenv("POSTGRES_DB", "app"),
                    "user": os.getenv("POSTGRES_USER", "postgres"),
                    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
                    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
                    "port": int(os.getenv("POSTGRES_PORT", "5432")),
                }
                self.postgres_sync = SessionPostgresSync(postgres_config, enabled=True)
                logger.info("✅ SessionStore initialized with PostgreSQL sync")
            except Exception as e:
                logger.warning(f"⚠️  PostgreSQL sync disabled: {e}")
                self.postgres_sync = None

    # ── Internals ──────────────────────────────────────────────────────────── #

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id               TEXT PRIMARY KEY,
                    name             TEXT,
                    title            TEXT NOT NULL,
                    objective        TEXT NOT NULL,
                    repo             TEXT,
                    branch           TEXT,
                    status           TEXT NOT NULL DEFAULT 'active',
                    progress         TEXT,
                    started_at       TEXT NOT NULL,
                    last_updated_at  TEXT NOT NULL,
                    ended_at         TEXT
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL REFERENCES sessions(id),
                    summary     TEXT NOT NULL,
                    context_json TEXT,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL REFERENCES sessions(id),
                    type        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id            TEXT NOT NULL REFERENCES sessions(id),
                    title                 TEXT NOT NULL,
                    description           TEXT,
                    status                TEXT NOT NULL DEFAULT 'pending',
                    sort_order            INTEGER NOT NULL DEFAULT 0,
                    result                TEXT,
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
                    session_id  TEXT NOT NULL REFERENCES sessions(id),
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
            """)
            # Migration segura: adiciona colunas que não existirem em DBs legados
            session_cols = {
                r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "name" not in session_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN name TEXT")
            if "branch" not in session_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN branch TEXT")
            if "base_branch" not in session_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN base_branch TEXT")

            task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "commit_sha" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN commit_sha TEXT")
            if "commit_message" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN commit_message TEXT")
            if "needs_human_decision" not in task_cols:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN needs_human_decision INTEGER NOT NULL DEFAULT 0"
                )
            if "decision" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN decision TEXT")
            if "decided_at" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN decided_at TEXT")
            if "decision_notes" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN decision_notes TEXT")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self) -> str:
        return f"sess_{uuid.uuid4().hex[:8]}"

    def _row_to_session(self, row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
        d = dict(row)
        cp = conn.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (d["id"],),
        ).fetchone()
        d["last_checkpoint"] = dict(cp) if cp else None
        d["artifacts_count"] = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE session_id = ?", (d["id"],)
        ).fetchone()[0]
        d["tasks_summary"] = self._tasks_summary(conn, d["id"])
        d["service_dependencies"] = self._list_service_deps(conn, d["id"])
        return d

    def _list_service_deps(
        self,
        conn: sqlite3.Connection,
        session_id: str,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM session_services WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _tasks_summary(self, conn: sqlite3.Connection, session_id: str) -> dict[str, int]:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE session_id = ? GROUP BY status",
            (session_id,),
        ).fetchall()
        summary = {s: 0 for s in TASK_STATUSES}
        summary["total"] = 0
        for r in rows:
            summary[r["status"]] = r["n"]
            summary["total"] += r["n"]
        return summary

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    # ── Sessions ───────────────────────────────────────────────────────────── #

    def create_session(
        self,
        title: str,
        objective: str,
        repo: str,
        branch: str | None = None,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        """Cria uma sessão. `repo` (owner repo) é obrigatório.
        `branch` é a branch da SESSÃO (criada via deploy-mcp). `base_branch` é
        a branch a partir da qual a branch da sessão foi criada."""
        session_id = self._new_id()
        name = _generate_name()
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO sessions (id, name, title, objective, repo, branch,
                   base_branch, status, started_at, last_updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (session_id, name, title, objective, repo, branch, base_branch, now, now),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            session_dict = self._row_to_session(row, conn)

            # Sync to PostgreSQL (Phase 2)
            if self.postgres_sync:
                self.postgres_sync.sync_session_created({
                    'id': session_id,
                    'title': title,
                    'objective': objective,
                    'status': 'active',
                    'repository_id': None,  # Will be linked later
                    'started_at': now,
                    'last_updated_at': now,
                })

            return session_dict

    def set_session_branch(
        self,
        session_id: str,
        branch: str,
        base_branch: str,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET branch = ?, base_branch = ?, last_updated_at = ? WHERE id = ?",
                (branch, base_branch, self._now(), session_id),
            )

    def get_session_name(self, session_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT name FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return row["name"] if row else None

    def list_sessions_without_branch(
        self,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status = ? AND (branch IS NULL OR branch = '') "
                "AND repo IS NOT NULL AND repo != ''",
                (status,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            return self._row_to_session(row, conn)

    def list_sessions(
        self,
        status: str | None = None,
        repo: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
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
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_session(r, conn) for r in rows]

    def update_session(
        self,
        session_id: str,
        status: str | None = None,
        progress: str | None = None,
    ) -> dict[str, Any] | None:
        now = self._now()
        updates = ["last_updated_at = ?"]
        params: list[Any] = [now]
        if status:
            updates.append("status = ?")
            params.append(status)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        params.append(session_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            session_dict = self._row_to_session(row, conn)

            # Sync to PostgreSQL (Phase 2)
            if self.postgres_sync:
                sync_updates = {}
                if status:
                    sync_updates['status'] = status
                if progress is not None:
                    sync_updates['progress'] = progress
                if sync_updates:
                    sync_updates['last_updated_at'] = now
                    self.postgres_sync.sync_session_updated(session_id, sync_updates)

            return session_dict

    def end_session(
        self,
        session_id: str,
        final_summary: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Encerra a sessão.
        Retorna:
          - dict (sessão) em caso de sucesso
          - list[dict] com tasks abertas se houver pendências (sessão não foi encerrada)
          - None se a sessão não existe
        """
        now = self._now()
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            placeholders = ",".join("?" for _ in TASK_OPEN_STATUSES)
            open_rows = conn.execute(
                f"SELECT * FROM tasks WHERE session_id = ? AND status IN ({placeholders}) "
                "ORDER BY sort_order ASC, id ASC",
                (session_id, *TASK_OPEN_STATUSES),
            ).fetchall()
            if open_rows:
                return [self._row_to_task(r) for r in open_rows]
            conn.execute(
                "UPDATE sessions SET status = 'completed', ended_at = ?, last_updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )
            if final_summary:
                conn.execute(
                    "INSERT INTO checkpoints (session_id, summary, created_at) VALUES (?, ?, ?)",
                    (session_id, f"[FINAL] {final_summary}", now),
                )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            session_dict = self._row_to_session(row, conn)

            # Sync to PostgreSQL (Phase 2)
            if self.postgres_sync:
                self.postgres_sync.sync_session_updated(session_id, {
                    'status': 'completed',
                    'ended_at': now,
                    'last_updated_at': now,
                })

            return session_dict

    # ── Checkpoints ────────────────────────────────────────────────────────── #

    def save_checkpoint(
        self,
        session_id: str,
        summary: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        context_json = json.dumps(context, ensure_ascii=False) if context else None
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "INSERT INTO checkpoints (session_id, summary, context_json, created_at) VALUES (?, ?, ?, ?)",
                (session_id, summary, context_json, now),
            )
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            checkpoint_id = result.lastrowid

        # Sync to PostgreSQL (Phase 2)
        if self.postgres_sync:
            self.postgres_sync.adapter.sync_to_postgres('checkpoints', {
                'session_id': session_id,
                'summary': summary,
                'context_snapshot': context,
                'created_by_id': 1,
                'created_at': now,
            })

        return {
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "summary": summary,
            "saved_at": now,
        }

    # ── Artifacts ──────────────────────────────────────────────────────────── #

    def add_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "INSERT INTO artifacts (session_id, type, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, artifact_type, content, now),
            )
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            artifact_id = result.lastrowid

        # Sync to PostgreSQL (Phase 2)
        if self.postgres_sync:
            self.postgres_sync.adapter.sync_to_postgres('artifacts', {
                'session_id': session_id,
                'artifact_type': artifact_type,
                'content': content,
                'metadata': {},
                'created_at': now,
            })

        return {
            "artifact_id": artifact_id,
            "session_id": session_id,
            "type": artifact_type,
            "content": content,
            "created_at": now,
        }

    # ── Tasks ──────────────────────────────────────────────────────────────── #

    def create_task(
        self,
        session_id: str,
        title: str,
        description: str | None = None,
        needs_human_decision: bool = False,
    ) -> dict[str, Any] | None:
        now = self._now()
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            cur = conn.execute(
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
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
            task_dict = self._row_to_task(row)

            # Sync to PostgreSQL (Phase 2)
            if self.postgres_sync:
                self.postgres_sync.sync_task_created(session_id, {
                    'title': title,
                    'description': description or '',
                    'status': 'pending',
                    'needs_human_decision': needs_human_decision,
                    'created_at': now,
                })

            return task_dict

    def create_tasks(
        self,
        session_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if not tasks:
            return []
        now = self._now()
        created: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            for offset, item in enumerate(tasks):
                cur = conn.execute(
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
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)
                ).fetchone()
                created.append(self._row_to_task(row))
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return created

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None

    def get_task_with_session(
        self, task_id: int
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Retorna (task, session) para o task — útil quando precisamos do repo/branch
        antes de fazer transição."""
        with self._lock, self._connect() as conn:
            t = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not t:
                return None
            s = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (t["session_id"],)
            ).fetchone()
            return (self._row_to_task(t), dict(s)) if s else None

    def list_tasks(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]] | None:
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            query = "SELECT * FROM tasks WHERE session_id = ?"
            params: list[Any] = [session_id]
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY sort_order ASC, id ASC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_task(r) for r in rows]

    def open_tasks(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            placeholders = ",".join("?" for _ in TASK_OPEN_STATUSES)
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE session_id = ? AND status IN ({placeholders}) "
                "ORDER BY sort_order ASC, id ASC",
                (session_id, *TASK_OPEN_STATUSES),
            ).fetchall()
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
        """Aplica uma transição de estado. Retorna o task atualizado, None se não existe,
        ou string com o estado atual quando a transição não é permitida."""
        now = self._now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
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
            conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, row["session_id"]),
            )
            updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            task_dict = self._row_to_task(updated)

            # Sync to PostgreSQL (Phase 2)
            if self.postgres_sync:
                sync_updates = {'status': new_status}
                if set_started_at and not row["started_at"]:
                    sync_updates['started_at'] = now
                if set_completed_at:
                    sync_updates['completed_at'] = now
                if result is not None:
                    sync_updates['result'] = result
                self.postgres_sync.sync_task_updated(task_id, sync_updates)

            return task_dict

    def start_task(self, task_id: int) -> dict[str, Any] | str | None:
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
        return self._transition_task(
            task_id,
            new_status="failed",
            allowed_from=("pending", "in_progress"),
            result=reason,
            set_completed_at=True,
        )

    def cancel_task(
        self,
        task_id: int,
        reason: str | None = None,
    ) -> dict[str, Any] | str | None:
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
        """Registra a decisão humana sobre uma task.
        decision='go'    → marca decision='go', task fica pending mas liberada para start_task.
        decision='no_go' → cancela a task usando notes como reason."""
        now = self._now()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            if row["status"] not in ("pending",):
                return row["status"]
            if decision == "go":
                conn.execute(
                    """UPDATE tasks SET decision='go', decided_at=?, decision_notes=?
                       WHERE id=?""",
                    (now, notes, task_id),
                )
            elif decision == "no_go":
                conn.execute(
                    """UPDATE tasks SET decision='no_go', decided_at=?, decision_notes=?,
                       status='cancelled', completed_at=?, result=?
                       WHERE id=?""",
                    (now, notes, now, notes or "no_go (human decision)", task_id),
                )
            else:
                raise ValueError(f"decision inválida: '{decision}'")
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, row["session_id"]),
            )
            updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(updated)

    # ── Service dependencies ───────────────────────────────────────────────── #

    def add_service_dependency(
        self,
        session_id: str,
        service: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Vincula um serviço auxiliar (do registry do services-mcp) à sessão.
        Retorna o registro criado, 'duplicate' se o serviço já estiver vinculado,
        ou None se a sessão não existe."""
        now = self._now()
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            existing = conn.execute(
                "SELECT 1 FROM session_services WHERE session_id = ? AND service = ?",
                (session_id, service),
            ).fetchone()
            if existing:
                return "duplicate"
            cur = conn.execute(
                """INSERT INTO session_services (session_id, service, role, notes, added_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, service, role, notes, now),
            )
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            row = conn.execute(
                "SELECT * FROM session_services WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_service_dependencies(
        self,
        session_id: str,
    ) -> list[dict[str, Any]] | None:
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            return self._list_service_deps(conn, session_id)

    def remove_service_dependency(
        self,
        session_id: str,
        service: str,
    ) -> bool | None:
        """Remove um vínculo. Retorna True se removeu, False se não existia,
        None se a sessão não existe."""
        now = self._now()
        with self._lock, self._connect() as conn:
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                return None
            cur = conn.execute(
                "DELETE FROM session_services WHERE session_id = ? AND service = ?",
                (session_id, service),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            return True

    # ── Suggestions ────────────────────────────────────────────────────────── #

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
        now = self._now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
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
            row = conn.execute(
                "SELECT * FROM suggestions WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def get_suggestion(self, suggestion_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_suggestions(
        self,
        target_repo: str | None = None,
        source_repo: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
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
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def count_pending_suggestions(self, target_repo: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM suggestions WHERE target_repo = ? AND status = 'pending'",
                (target_repo,),
            ).fetchone()
            return row["n"]

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
        ou string com status atual se transição é inválida."""
        now = self._now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
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
            conn.execute(
                f"UPDATE suggestions SET {', '.join(updates)} WHERE id = ?", params
            )
            updated = conn.execute(
                "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            return dict(updated)

    # ── Decisions (audit trail) ────────────────────────────────────────────── #

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
        now = self._now()
        ctx_json = json.dumps(context, ensure_ascii=False) if context else None
        with self._lock, self._connect() as conn:
            cur = conn.execute(
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
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
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
        with self._lock, self._connect() as conn:
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
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            return dict(row) if row else None

    # ── Resume ─────────────────────────────────────────────────────────────── #

    def get_resume_context(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            session = dict(row)

            # Últimos 5 checkpoints (mais recente primeiro)
            cps = conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT 5",
                (session_id,),
            ).fetchall()
            checkpoints = [dict(c) for c in cps]

            # Últimos 20 artefatos
            arts = conn.execute(
                "SELECT * FROM artifacts WHERE session_id = ? ORDER BY id DESC LIMIT 20",
                (session_id,),
            ).fetchall()
            artifacts = [dict(a) for a in arts]

            # Tasks abertas (pending + in_progress)
            placeholders = ",".join("?" for _ in TASK_OPEN_STATUSES)
            open_rows = conn.execute(
                f"SELECT * FROM tasks WHERE session_id = ? AND status IN ({placeholders}) "
                "ORDER BY sort_order ASC, id ASC",
                (session_id, *TASK_OPEN_STATUSES),
            ).fetchall()
            open_tasks = [dict(t) for t in open_rows]
            tasks_summary = self._tasks_summary(conn, session_id)

            # Service dependencies (services auxiliares do services-mcp)
            service_deps = self._list_service_deps(conn, session_id)

            # Pending suggestions cross-repo dirigidas ao repo da sessão
            pending_suggestions: list[dict[str, Any]] = []
            pending_count = 0
            if session.get("repo"):
                pending_count_row = conn.execute(
                    "SELECT COUNT(*) AS n FROM suggestions WHERE target_repo = ? AND status = 'pending'",
                    (session["repo"],),
                ).fetchone()
                pending_count = pending_count_row["n"]
                pending_rows = conn.execute(
                    "SELECT * FROM suggestions WHERE target_repo = ? AND status = 'pending' "
                    "ORDER BY created_at DESC LIMIT 5",
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
