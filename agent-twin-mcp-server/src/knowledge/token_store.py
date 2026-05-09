"""TokenStore — tabela SQLite de tokens de usuários/agentes (bcrypt).

Schema:
  id            INTEGER PK AUTOINCREMENT
  token         TEXT UNIQUE    — bcrypt hash do token portador (nunca plaintext)
  token_prefix  TEXT           — primeiros 8 chars do token original (lookup rápido)
  user_id       TEXT           — identificador único do usuário/agente
  name          TEXT           — nome de exibição
  email         TEXT           — email
  role          TEXT           — developer | admin | agent | readonly
  scopes        TEXT           — JSON: ["deploy", "qa", "config", "infra", "*"]
  environment   TEXT           — dev | staging | production
  tenant_id     TEXT           — nullable
  active        INTEGER        — 1=ativo, 0=revogado
  created_at    TEXT           — ISO 8601
  last_used_at  TEXT           — ISO 8601 (nullable)
  expires_at    TEXT           — ISO 8601 (nullable — NULL = sem expiração)

Segurança:
  - Tokens armazenados como bcrypt hash (rounds=10); nunca em plaintext.
  - validate() faz lookup por token_prefix (índice) + bcrypt.checkpw().
  - Tokens antigos sem token_prefix são invalidados automaticamente na migration.
"""
from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt

_log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token        TEXT    UNIQUE NOT NULL,
    token_prefix TEXT,
    user_id      TEXT           NOT NULL,
    name         TEXT           NOT NULL,
    email        TEXT           NOT NULL,
    role         TEXT           NOT NULL DEFAULT 'developer',
    scopes       TEXT           NOT NULL DEFAULT '["*"]',
    environment  TEXT           NOT NULL DEFAULT 'dev',
    tenant_id    TEXT,
    active       INTEGER        NOT NULL DEFAULT 1,
    created_at   TEXT           NOT NULL,
    last_used_at TEXT,
    expires_at   TEXT
)
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_token_prefix ON tokens(token_prefix);
CREATE INDEX IF NOT EXISTS idx_user_id      ON tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_active       ON tokens(active);
CREATE INDEX IF NOT EXISTS idx_tenant_id    ON tokens(tenant_id);
CREATE INDEX IF NOT EXISTS idx_expires_at   ON tokens(expires_at);
"""

_MIGRATE_ADD_TENANT = "ALTER TABLE tokens ADD COLUMN tenant_id TEXT"
_MIGRATE_ADD_PREFIX = "ALTER TABLE tokens ADD COLUMN token_prefix TEXT"


class TokenStoreError(RuntimeError):
    pass


class TokenStore:
    """Gerencia tokens de autenticação em SQLite (armazenados como bcrypt hash)."""

    def __init__(self, db_path: str) -> None:
        self._db = Path(db_path).expanduser().resolve()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        _log.info("token_store_ready path=%s", self._db)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)
            # Migrações incrementais (antes dos índices — colunas devem existir)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(tokens)").fetchall()}
            if "tenant_id" not in cols:
                conn.execute(_MIGRATE_ADD_TENANT)
                _log.info("token_store_migrated: added tenant_id column")
            if "token_prefix" not in cols:
                conn.execute(_MIGRATE_ADD_PREFIX)
                # Tokens sem hash bcrypt (plaintext antigos) são invalidados
                conn.execute("UPDATE tokens SET active = 0 WHERE token_prefix IS NULL")
                _log.info(
                    "token_store_migrated: added token_prefix, invalidated plaintext tokens"
                )
            # Índices para performance (após migrations para garantir colunas existem)
            for stmt in _CREATE_INDEXES.strip().splitlines():
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)

    # ── Validação ─────────────────────────────────────────────────────────── #

    def validate(self, token: str) -> dict[str, Any] | None:
        """Valida o token e retorna o registro do usuário ou None.

        Usa lookup por prefix (índice) + bcrypt.checkpw para verificação segura.
        Retorna None se: token não existe, active=0, expirado ou bcrypt falha.
        """
        prefix = token[:8]
        now = datetime.now(timezone.utc)

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tokens WHERE token_prefix = ? AND active = 1",
                (prefix,),
            ).fetchall()

        for row in rows:
            record = dict(row)
            # Checa expiração
            if record["expires_at"]:
                expires = datetime.fromisoformat(record["expires_at"])
                if now > expires:
                    _log.warning("token_expired user_id=%s", record["user_id"])
                    continue
            # Verificação bcrypt
            try:
                if bcrypt.checkpw(token.encode(), record["token"].encode()):
                    return record
            except Exception:  # noqa: BLE001
                continue
                continue

        return None

    # ── CRUD ──────────────────────────────────────────────────────────────── #

    def register(
        self,
        name: str,
        email: str,
        role: str = "developer",
        environment: str = "dev",
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Cria um novo token e retorna o registro completo.

        O token plaintext é retornado **apenas uma vez** — não é armazenado no DB.
        O DB armazena somente o bcrypt hash e o prefix para lookup.
        """
        token = secrets.token_urlsafe(32)
        token_prefix = token[:8]
        token_hash = bcrypt.hashpw(token.encode(), bcrypt.gensalt(rounds=10)).decode()
        user_id = secrets.token_hex(8)
        now = datetime.now(timezone.utc).isoformat()
        expires_at = None
        if expires_in_days:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            ).isoformat()

        scopes_json = json.dumps(scopes or ["*"])

        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO tokens
                       (token, token_prefix, user_id, name, email, role, scopes, environment,
                        tenant_id, active, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        token_hash, token_prefix, user_id, name, email, role,
                        scopes_json, environment, tenant_id, now, expires_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise TokenStoreError(f"Erro ao registrar token: {exc}") from exc

        _log.info(
            "token_registered user_id=%s name=%s role=%s tenant_id=%s",
            user_id, name, role, tenant_id,
        )
        return {
            "token": token,  # plaintext — retornado apenas uma vez
            "user_id": user_id,
            "name": name,
            "email": email,
            "role": role,
            "scopes": scopes or ["*"],
            "environment": environment,
            "tenant_id": tenant_id,
            "created_at": now,
            "expires_at": expires_at,
        }

    def revoke(self, identifier: str) -> dict[str, Any]:
        """Revoga por user_id (preferencial) ou por token bruto.

        Retorna quantos registros foram afetados.
        """
        with self._conn() as conn:
            # Tenta por user_id primeiro (mais eficiente — usa índice)
            cur = conn.execute(
                "UPDATE tokens SET active = 0 WHERE user_id = ? AND active = 1",
                (identifier,),
            )
            affected = cur.rowcount

            if affected == 0:
                # Tentativa por token bruto: prefix lookup + bcrypt
                prefix = identifier[:8]
                rows = conn.execute(
                    "SELECT id, token FROM tokens WHERE token_prefix = ? AND active = 1",
                    (prefix,),
                ).fetchall()
                for row in rows:
                    try:
                        if bcrypt.checkpw(identifier.encode(), row["token"].encode()):
                            conn.execute(
                                "UPDATE tokens SET active = 0 WHERE id = ?", (row["id"],)
                            )
                            affected = 1
                            break
                    except Exception:  # noqa: BLE001
                        continue

        _log.info("token_revoked identifier=%s affected=%d", identifier, affected)
        return {"revoked": affected > 0, "affected": affected, "identifier": identifier}

    def rotate(self, identifier: str) -> dict[str, Any]:
        """Revoga o token atual do user_id e emite um novo para o mesmo usuário.

        Args:
            identifier: user_id do usuário a ter o token rotacionado.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tokens WHERE user_id = ? AND active = 1",
                (identifier,),
            ).fetchone()
            if not row:
                raise TokenStoreError(
                    f"user_id '{identifier}' não encontrado ou já revogado."
                )
            record = dict(row)
            # Revoga dentro da mesma conexão (2 round trips → 1 transação)
            conn.execute(
                "UPDATE tokens SET active = 0 WHERE user_id = ? AND active = 1",
                (identifier,),
            )

        return self.register(
            name=record["name"],
            email=record["email"],
            role=record["role"],
            environment=record["environment"],
            scopes=json.loads(record["scopes"]),
            tenant_id=record.get("tenant_id"),
        )

    def touch(self, user_id: str) -> None:
        """Atualiza last_used_at para o usuário."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE tokens SET last_used_at = ? WHERE user_id = ? AND active = 1",
                (now, user_id),
            )

    def list_all(
        self,
        include_revoked: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lista tokens sem expor token plaintext nem token hash.

        Nunca retorna as colunas `token` ou `token_prefix`.
        """
        cols = (
            "id, user_id, name, email, role, scopes, environment, tenant_id, "
            "active, created_at, last_used_at, expires_at"
        )
        if not include_revoked:
            query = (
                f"SELECT {cols} FROM tokens WHERE active = 1 "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?"
            )
        else:
            query = (
                f"SELECT {cols} FROM tokens "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?"
            )
        with self._conn() as conn:
            rows = conn.execute(query, (limit, offset)).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r["scopes"] = json.loads(r["scopes"])
            result.append(r)
        return result
