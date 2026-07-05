"""User store para o login da tela de consentimento do auth-mcp.

Autenticação de usuário final (dono do browser) que aprova o consentimento OAuth.
Substitui o `username` livre por credenciais reais verificadas com bcrypt.

Duas implementações com a mesma interface:
- InMemoryUserStore — dev/teste (seed via AS_DEV_USER/AS_DEV_PASSWORD).
- PostgresUserStore — produção (tabela `auth_users`).

Nota: este é o login LOCAL. Para SSO corporativo, o auth-mcp também suporta federação
OIDC upstream (ver `oidc_upstream.py` / AS_UPSTREAM_OIDC_*), que dispensa este store.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

import bcrypt


@dataclass
class User:
    username: str
    password_hash: bytes
    subject: str                 # vira o `sub` do token (ex: "user:alice")
    role: str = "user"
    tenant_id: str = "default"
    disabled: bool = False


class UserStore:
    """Interface mínima; implementada por InMemory e Postgres."""

    def get_user(self, username: str) -> User | None:  # pragma: no cover - interface
        raise NotImplementedError

    def verify(self, username: str, password: str) -> User | None:
        """Retorna o User se as credenciais conferem e a conta está ativa; senão None.

        Faz um checkpw dummy quando o usuário não existe para reduzir o oráculo de
        timing (não revelar se o usuário existe pelo tempo de resposta).
        """
        user = self.get_user(username)
        if user is None or user.disabled:
            bcrypt.checkpw(b"dummy", _DUMMY_HASH)  # iguala custo aproximado
            return None
        if bcrypt.checkpw(password.encode(), user.password_hash):
            return user
        return None

    @staticmethod
    def hash_password(raw: str) -> bytes:
        return bcrypt.hashpw(raw.encode(), bcrypt.gensalt())


_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt())


class InMemoryUserStore(UserStore):
    def __init__(self, users: list[User] | None = None):
        self._users: dict[str, User] = {u.username: u for u in (users or [])}

    def add(self, user: User) -> None:
        self._users[user.username] = user

    def get_user(self, username: str) -> User | None:
        return self._users.get(username)


USERS_DDL = """
CREATE TABLE IF NOT EXISTS auth_users (
    username       TEXT PRIMARY KEY,
    password_hash  BYTEA NOT NULL,
    subject        TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'user',
    tenant_id      TEXT NOT NULL DEFAULT 'default',
    disabled       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
"""


class PostgresUserStore(UserStore):
    def __init__(self, conn_params: dict):
        import psycopg2
        self._psycopg2 = psycopg2
        self.conn_params = conn_params
        conn = psycopg2.connect(**conn_params)
        try:
            with conn.cursor() as cur:
                cur.execute(USERS_DDL)
            conn.commit()
        finally:
            conn.close()

    def get_user(self, username: str) -> User | None:
        conn = self._psycopg2.connect(**self.conn_params)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username, password_hash, subject, role, tenant_id, disabled "
                    "FROM auth_users WHERE username = %s", [username])
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return User(username=row[0], password_hash=bytes(row[1]), subject=row[2],
                    role=row[3], tenant_id=row[4], disabled=row[5])


def make_user_store() -> UserStore:
    if os.getenv("USER_STORE", "").lower() == "postgres":
        try:
            params = {
                "host": os.getenv("PG_HOST", "postgres"),
                "port": int(os.getenv("PG_PORT", "5432")),
                "user": os.getenv("PG_USER", "platform"),
                "password": os.getenv("PG_PASSWORD", ""),
                "database": os.getenv("PG_DB", "platform"),
                "connect_timeout": 5,
            }
            return PostgresUserStore(params)
        except Exception as e:  # pragma: no cover
            print(f"⚠️  User store Postgres indisponível ({e}); usando in-memory.", file=sys.stderr)

    # Dev fallback: seed de um usuário a partir do env (com aviso).
    dev_user = os.getenv("AS_DEV_USER", "dev")
    dev_pass = os.getenv("AS_DEV_PASSWORD", "dev-password-change-me")
    print(f"⚠️  USER_STORE não é postgres — seed de usuário DEV '{dev_user}' (só dev).", file=sys.stderr)
    return InMemoryUserStore([
        User(username=dev_user, password_hash=UserStore.hash_password(dev_pass),
             subject=f"user:{dev_user}", role="developer", tenant_id="dev"),
    ])
