"""TokenStore — tabela PostgreSQL de tokens de usuários/agentes (bcrypt).

Schema:
  id            SERIAL PK
  token         TEXT UNIQUE    — bcrypt hash do token portador (nunca plaintext)
  token_prefix  TEXT           — primeiros 8 chars do token original (lookup rápido)
  user_id       TEXT           — identificador único do usuário/agente
  name          TEXT           — nome de exibição
  email         TEXT           — email
  role          TEXT           — developer | admin | agent | readonly
  scopes        JSONB          — ["deploy", "qa", "config", "infra", "*"]
  environment   TEXT           — dev | staging | production
  tenant_id     TEXT           — nullable
  active        BOOLEAN        — true=ativo, false=revogado
  created_at    TIMESTAMPTZ    — timestamp com timezone
  last_used_at  TIMESTAMPTZ    — timestamp (nullable)
  expires_at    TIMESTAMPTZ    — timestamp (nullable — NULL = sem expiração)

Segurança:
  - Tokens armazenados como bcrypt hash (rounds=10); nunca em plaintext.
  - validate() faz lookup por token_prefix (índice) + bcrypt.checkpw().
  - Tokens antigos sem token_prefix são invalidados automaticamente na migration.
"""
from __future__ import annotations

import json
import logging
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import psycopg2
import psycopg2.extras
import psycopg2.pool

from ..config.settings import AgentTwinSettings

_log = logging.getLogger(__name__)


class TokenStoreError(RuntimeError):
    pass


class TokenStore:
    """Gerencia tokens de autenticação em PostgreSQL (armazenados como bcrypt hash)."""

    def __init__(self, settings: AgentTwinSettings) -> None:
        self.settings = settings
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pg_min_conn,
            maxconn=settings.pg_max_conn,
            dsn=settings.pg_dsn,
        )
        self._init_schema()
        _log.info("token_store_ready pg_host=%s pg_db=%s", settings.pg_host, settings.pg_db)

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
            _log.info("TokenStore connection pool closed")

    def _init_schema(self) -> None:
        """Cria tabela de tokens se não existir."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agent_tokens (
                        id SERIAL PRIMARY KEY,
                        token TEXT UNIQUE NOT NULL,
                        token_prefix TEXT,
                        user_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'developer',
                        scopes JSONB NOT NULL DEFAULT '["*"]',
                        environment TEXT NOT NULL DEFAULT 'dev',
                        tenant_id TEXT,
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_used_at TIMESTAMPTZ,
                        expires_at TIMESTAMPTZ
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_tokens_prefix ON agent_tokens(token_prefix)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_tokens_user_id ON agent_tokens(user_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_tokens_active ON agent_tokens(active)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_tokens_tenant_id ON agent_tokens(tenant_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_tokens_expires_at ON agent_tokens(expires_at)"
                )

    # ── Validação ─────────────────────────────────────────────────────────── #

    def validate(self, token: str) -> dict[str, Any] | None:
        """Valida o token e retorna o registro do usuário ou None.

        Usa lookup por prefix (índice) + bcrypt.checkpw para verificação segura.
        Retorna None se: token não existe, active=false, expirado ou bcrypt falha.
        """
        prefix = token[:8]
        now = datetime.now(timezone.utc)

        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM agent_tokens WHERE token_prefix = %s AND active = TRUE",
                    (prefix,),
                )
                rows = cur.fetchall()

        for row in rows:
            record = dict(row)
            # Checa expiração
            if record["expires_at"]:
                expires = record["expires_at"]
                if now > expires:
                    _log.warning("token_expired user_id=%s", record["user_id"])
                    continue
            # Verificação bcrypt
            try:
                if bcrypt.checkpw(token.encode(), record["token"].encode()):
                    return record
            except Exception:  # noqa: BLE001
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
        now = datetime.now(timezone.utc)
        expires_at = None
        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)

        scopes_json = json.dumps(scopes or ["*"])

        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO agent_tokens
                           (token, token_prefix, user_id, name, email, role, scopes, environment,
                            tenant_id, active, created_at, expires_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)""",
                        (
                            token_hash, token_prefix, user_id, name, email, role,
                            scopes_json, environment, tenant_id, now, expires_at,
                        ),
                    )
        except psycopg2.IntegrityError as exc:
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
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

    def revoke(self, identifier: str) -> dict[str, Any]:
        """Revoga por user_id (preferencial) ou por token bruto.

        Retorna quantos registros foram afetados.
        """
        affected = 0
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                # Tenta por user_id primeiro (mais eficiente — usa índice)
                cur.execute(
                    "UPDATE agent_tokens SET active = FALSE WHERE user_id = %s AND active = TRUE",
                    (identifier,),
                )
                affected = cur.rowcount

                if affected == 0:
                    # Tentativa por token bruto: prefix lookup + bcrypt
                    prefix = identifier[:8]
                    cur.execute(
                        "SELECT id, token FROM agent_tokens WHERE token_prefix = %s AND active = TRUE",
                        (prefix,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        try:
                            if bcrypt.checkpw(identifier.encode(), row[1].encode()):
                                cur.execute(
                                    "UPDATE agent_tokens SET active = FALSE WHERE id = %s", (row[0],)
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
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM agent_tokens WHERE user_id = %s AND active = TRUE",
                    (identifier,),
                )
                row = cur.fetchone()
                if not row:
                    raise TokenStoreError(
                        f"user_id '{identifier}' não encontrado ou já revogado."
                    )
                record = dict(row)
                # Revoga dentro da mesma conexão (2 round trips → 1 transação)
                cur.execute(
                    "UPDATE agent_tokens SET active = FALSE WHERE user_id = %s AND active = TRUE",
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
        now = datetime.now(timezone.utc)
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_tokens SET last_used_at = %s WHERE user_id = %s AND active = TRUE",
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
        if not include_revoked:
            query = (
                "SELECT id, user_id, name, email, role, scopes, environment, tenant_id, "
                "active, created_at, last_used_at, expires_at FROM agent_tokens WHERE active = TRUE "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s"
            )
        else:
            query = (
                "SELECT id, user_id, name, email, role, scopes, environment, tenant_id, "
                "active, created_at, last_used_at, expires_at FROM agent_tokens "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s"
            )
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (limit, offset))
                rows = cur.fetchall()

        result = []
        for row in rows:
            r = dict(row)
            r["scopes"] = json.loads(r["scopes"])
            result.append(r)
        return result
