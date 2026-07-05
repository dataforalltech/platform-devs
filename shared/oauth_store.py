"""Persistência OAuth para o Authorization Server (auth-mcp).

Guarda clients (Dynamic Client Registration), authorization codes (single-use, TTL curto)
e refresh tokens (com rotação). Duas implementações com a MESMA interface:

- InMemoryOAuthStore — dev/teste, sem dependências.
- PostgresOAuthStore — produção (tabelas oauth_clients / oauth_auth_codes / oauth_refresh_tokens).

Selecione via `make_store()` (env OAUTH_STORE=postgres + PG_*). Fallback: in-memory com aviso.

Nota: expiração de auth codes/refresh é aplicada na leitura (take_*), e no Postgres com índice
por expires_at para limpeza. Auth codes e refresh são single-use (deletados no take → rotação).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class OAuthClient:
    client_id: str
    client_secret_hash: bytes | None       # None → public client (usa PKCE, sem secret)
    redirect_uris: list[str]
    scopes: list[str]
    grant_types: list[str] = field(default_factory=lambda: ["authorization_code", "refresh_token"])
    token_endpoint_auth_method: str = "none"
    client_name: str = ""
    subject: str = ""                        # sujeito default (p/ client_credentials de serviço)

    @property
    def is_public(self) -> bool:
        return self.client_secret_hash is None or self.token_endpoint_auth_method == "none"


class OAuthStore(Protocol):
    def create_client(self, client: OAuthClient) -> None: ...
    def get_client(self, client_id: str) -> OAuthClient | None: ...
    def save_auth_code(self, code: str, data: dict[str, Any], ttl: int) -> None: ...
    def take_auth_code(self, code: str) -> dict[str, Any] | None: ...
    def save_refresh(self, token: str, data: dict[str, Any], ttl: int) -> None: ...
    def take_refresh(self, token: str) -> dict[str, Any] | None: ...


# ============================================================================
# In-memory
# ============================================================================

class InMemoryOAuthStore:
    def __init__(self) -> None:
        self._clients: dict[str, OAuthClient] = {}
        self._codes: dict[str, tuple[dict[str, Any], float]] = {}
        self._refresh: dict[str, tuple[dict[str, Any], float]] = {}

    def create_client(self, client: OAuthClient) -> None:
        self._clients[client.client_id] = client

    def get_client(self, client_id: str) -> OAuthClient | None:
        return self._clients.get(client_id)

    def save_auth_code(self, code: str, data: dict[str, Any], ttl: int) -> None:
        self._codes[code] = (data, time.time() + ttl)

    def take_auth_code(self, code: str) -> dict[str, Any] | None:
        entry = self._codes.pop(code, None)
        if not entry:
            return None
        data, exp = entry
        return data if time.time() < exp else None

    def save_refresh(self, token: str, data: dict[str, Any], ttl: int) -> None:
        self._refresh[token] = (data, time.time() + ttl)

    def take_refresh(self, token: str) -> dict[str, Any] | None:
        entry = self._refresh.pop(token, None)
        if not entry:
            return None
        data, exp = entry
        return data if time.time() < exp else None


# ============================================================================
# Postgres
# ============================================================================

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id           TEXT PRIMARY KEY,
    client_secret_hash  BYTEA,
    redirect_uris       JSONB NOT NULL DEFAULT '[]',
    scopes              JSONB NOT NULL DEFAULT '[]',
    grant_types         JSONB NOT NULL DEFAULT '[]',
    token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
    client_name         TEXT DEFAULT '',
    subject             TEXT DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oauth_auth_codes (
    code        TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_codes_exp ON oauth_auth_codes (expires_at);
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    token       TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refresh_exp ON oauth_refresh_tokens (expires_at);
"""


class PostgresOAuthStore:
    def __init__(self, conn_params: dict[str, Any]):
        import psycopg2  # import tardio: só quando de fato usado
        self._psycopg2 = psycopg2
        self.conn_params = conn_params
        self._init_schema()

    def _conn(self):
        return self._psycopg2.connect(**self.conn_params)

    def _init_schema(self) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_DDL)
            conn.commit()
        finally:
            conn.close()

    def create_client(self, client: OAuthClient) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO oauth_clients
                       (client_id, client_secret_hash, redirect_uris, scopes, grant_types,
                        token_endpoint_auth_method, client_name, subject)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (client_id) DO NOTHING""",
                    [client.client_id,
                     self._psycopg2.Binary(client.client_secret_hash) if client.client_secret_hash else None,
                     json.dumps(client.redirect_uris), json.dumps(client.scopes),
                     json.dumps(client.grant_types), client.token_endpoint_auth_method,
                     client.client_name, client.subject],
                )
            conn.commit()
        finally:
            conn.close()

    def get_client(self, client_id: str) -> OAuthClient | None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT client_id, client_secret_hash, redirect_uris, scopes, grant_types,
                              token_endpoint_auth_method, client_name, subject
                       FROM oauth_clients WHERE client_id = %s""", [client_id])
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        secret = bytes(row[1]) if row[1] is not None else None
        return OAuthClient(
            client_id=row[0], client_secret_hash=secret,
            redirect_uris=row[2], scopes=row[3], grant_types=row[4],
            token_endpoint_auth_method=row[5], client_name=row[6], subject=row[7],
        )

    def save_auth_code(self, code: str, data: dict[str, Any], ttl: int) -> None:
        self._save("oauth_auth_codes", "code", code, data, ttl)

    def take_auth_code(self, code: str) -> dict[str, Any] | None:
        return self._take("oauth_auth_codes", "code", code)

    def save_refresh(self, token: str, data: dict[str, Any], ttl: int) -> None:
        self._save("oauth_refresh_tokens", "token", token, data, ttl)

    def take_refresh(self, token: str) -> dict[str, Any] | None:
        return self._take("oauth_refresh_tokens", "token", token)

    def _save(self, table: str, key_col: str, key: str, data: dict[str, Any], ttl: int) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {table} ({key_col}, data, expires_at) "
                    f"VALUES (%s, %s, NOW() + make_interval(secs => %s))",
                    [key, json.dumps(data), ttl])
            conn.commit()
        finally:
            conn.close()

    def _take(self, table: str, key_col: str, key: str) -> dict[str, Any] | None:
        # single-use: DELETE ... RETURNING, respeitando expiração
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {table} WHERE {key_col} = %s "
                    f"AND expires_at > NOW() RETURNING data", [key])
                row = cur.fetchone()
                # limpa expirados oportunisticamente
                cur.execute(f"DELETE FROM {table} WHERE expires_at <= NOW()")
            conn.commit()
        finally:
            conn.close()
        return row[0] if row else None


# ============================================================================
# Factory
# ============================================================================

def make_store() -> OAuthStore:
    if os.getenv("OAUTH_STORE", "").lower() == "postgres":
        try:
            params = {
                "host": os.getenv("PG_HOST", "postgres"),
                "port": int(os.getenv("PG_PORT", "5432")),
                "user": os.getenv("PG_USER", "platform"),
                "password": os.getenv("PG_PASSWORD", ""),
                "database": os.getenv("PG_DB", "platform"),
                "connect_timeout": 5,
            }
            return PostgresOAuthStore(params)
        except Exception as e:  # pragma: no cover - fallback defensivo
            print(f"⚠️  OAuth store Postgres indisponível ({e}); usando in-memory.", file=sys.stderr)
    return InMemoryOAuthStore()
