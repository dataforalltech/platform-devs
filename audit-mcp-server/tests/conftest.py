"""Fixtures da Suíte Canônica do audit-mcp (§16 — PA-01 / FID-02).

**Banco REAL, nunca mockado** (FID-02): os testes do store/tools/servidor rodam contra
um MySQL 8.x real com **2 tenants** (banco-por-tenant), exercitando o caminho canônico
`get_pool_for_tenant -> Repository -> dialeto MySQL`. O único "duplo" é o
``platform_lookup`` (linha estática que substitui a consulta ao admin-mysql PLATFORMS) —
a credencial do tenant, não o banco. RS256 é **real** (chave gerada, token assinado,
verificador real) — nunca bypass (STD-QA-001 / Test Doubles Policy).

Config via env (o CI provê o serviço MySQL):
  MYSQL_ROOT_PASSWORD  — senha root (obrigatória; sem ela os testes de DB são SKIPADOS)
  PILOT_MYSQL_HOST     — default 127.0.0.1
  PILOT_MYSQL_PORT     — default 3306

Os checkers do audit rodam sobre repos locais temporários (``tmp_repo``); os tools de
policy/checklist leem YAML do próprio repo — nada disso toca rede. O banco é que nunca
é mockado.
"""

from __future__ import annotations

import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiomysql
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from platform_core.request_context import reset_tenant_id, set_tenant_id
from platform_database import close_tenant_pools
from platform_database.orm import configure
from platform_database.orm.dialects import dialect_for_pool
from platform_database.orm.tenant import TenantSession
from platform_database.tenant_resolver import get_pool_for_tenant

# Garante que a raiz do audit-mcp-server esteja no sys.path (permite `from src...`
# mesmo quando o pytest é invocado de outro cwd, sem depender de `pip install -e .`).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config.settings import AuditSettings  # noqa: E402
from src.db.schema import (  # noqa: E402
    AUDIT_APPROVALS_TABLE,
    AUDIT_ITEMS_TABLE,
    AUDITS_TABLE,
    SERVICE_CRITICALITY_TABLE,
    ensure_schema,
)
from src.db.store import AuditStore  # noqa: E402

_HOST = os.environ.get("PILOT_MYSQL_HOST", "127.0.0.1")
_PORT = int(os.environ.get("PILOT_MYSQL_PORT", "3306"))
_PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")

_POLICIES_DIR = _ROOT / "src" / "policies"

TENANT_A = "audit_test_a"
TENANT_B = "audit_test_b"

_ALL_TABLES = (AUDIT_ITEMS_TABLE, AUDIT_APPROVALS_TABLE, AUDITS_TABLE, SERVICE_CRITICALITY_TABLE)


def _mysql_up() -> bool:
    if not _PW:
        return False
    try:
        with socket.create_connection((_HOST, _PORT), timeout=2):
            return True
    except OSError:
        return False


requires_mysql = pytest.mark.skipif(
    not _mysql_up(),
    reason="MySQL real indisponível (defina MYSQL_ROOT_PASSWORD/PILOT_MYSQL_HOST/PILOT_MYSQL_PORT)",
)


def _test_settings(**over: Any) -> AuditSettings:
    kw: dict[str, Any] = dict(
        MCP_TWIN_AUDIENCE="mcp:audit-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        DB_ENGINE="mysql",
        DB_HOST=_HOST,
        DB_PORT=_PORT,
        DB_USER="root",
        DB_PASSWORD=_PW,
        ADMIN_DB_HOST=_HOST,
        ADMIN_DB_PORT=_PORT,
        ADMIN_DB_USER="root",
        ADMIN_DB_PASSWORD=_PW,
        github_token="",
        policies_path=str(_POLICIES_DIR),
    )
    kw.update(over)
    return AuditSettings(**kw)


def _platform_row(tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "db_engine": "mysql",
        "db_host": _HOST,
        "db_port": _PORT,
        "db_name": tenant_id,  # banco-por-tenant: o db do tenant é o próprio id
        "db_user": "root",
        "db_password": _PW,
    }


async def _lookup(tenant_id: str, _settings: Any) -> dict[str, Any] | None:
    return _platform_row(tenant_id) if tenant_id in (TENANT_A, TENANT_B) else None


# Pools aiomysql são atados ao event loop. pytest-asyncio usa um loop por função;
# cada fixture cria os pools no loop do teste e `close_tenant_pools()` no teardown
# limpa o registry (close_all) p/ o próximo teste recriar no seu próprio loop.
async def _make_store(tenant_id: str) -> tuple[AuditStore, Any]:
    settings = _test_settings()
    conn = await aiomysql.connect(host=_HOST, port=_PORT, user="root", password=_PW, autocommit=True)
    try:
        async with conn.cursor() as cur:
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {tenant_id} CHARACTER SET utf8mb4")
    finally:
        conn.close()
    pool = await get_pool_for_tenant(settings, tenant_id, platform_lookup=_lookup, strict=True)
    await ensure_schema(pool, engine=dialect_for_pool(pool).name)
    # Estado limpo por teste (tabelas já existem; TRUNCATE é idempotente e rápido).
    for table in _ALL_TABLES:
        await pool.execute(f"TRUNCATE TABLE {table}")
    token = set_tenant_id(tenant_id)
    return AuditStore(TenantSession(pool, tenant_id)), token


@pytest_asyncio.fixture
async def store_a():
    store, token = await _make_store(TENANT_A)
    yield store
    reset_tenant_id(token)
    await close_tenant_pools()


@pytest_asyncio.fixture
async def store_b():
    store, token = await _make_store(TENANT_B)
    yield store
    reset_tenant_id(token)
    await close_tenant_pools()


@pytest_asyncio.fixture
async def seed_platforms():
    """Semeia ADMIN_DATAFORALL.PLATFORMS no MySQL de teste + `configure()`.

    Exercita o caminho credencial-zero REAL (for_tenant -> get_platform -> PLATFORMS),
    não o platform_lookup estático. A tabela é mínima (só as colunas que o resolver lê)."""
    from platform_tenant.platform_client import close_admin_pools, invalidate_cache

    conn = await aiomysql.connect(host=_HOST, port=_PORT, user="root", password=_PW, autocommit=True)
    try:
        async with conn.cursor() as cur:
            await cur.execute("CREATE DATABASE IF NOT EXISTS ADMIN_DATAFORALL CHARACTER SET utf8mb4")
            await cur.execute(
                """CREATE TABLE IF NOT EXISTS ADMIN_DATAFORALL.PLATFORMS (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    tenant_id VARCHAR(255) NOT NULL,
                    db_engine VARCHAR(32), db_host VARCHAR(255), db_port INT,
                    db_name VARCHAR(255), db_user VARCHAR(255), db_password VARCHAR(500),
                    active SMALLINT DEFAULT 1, excluded SMALLINT DEFAULT 0,
                    UNIQUE KEY uq_platforms_tenant (tenant_id))"""
            )
            for tid in (TENANT_A, TENANT_B):
                await cur.execute("DELETE FROM ADMIN_DATAFORALL.PLATFORMS WHERE tenant_id=%s", (tid,))
                await cur.execute(
                    "INSERT INTO ADMIN_DATAFORALL.PLATFORMS (tenant_id, db_engine, db_host, "
                    "db_port, db_name, db_user, db_password, active, excluded) "
                    "VALUES (%s,'mysql',%s,%s,%s,'root',%s,1,0)",
                    (tid, _HOST, _PORT, tid, _PW),
                )
                await cur.execute(f"CREATE DATABASE IF NOT EXISTS {tid} CHARACTER SET utf8mb4")
    finally:
        conn.close()

    invalidate_cache()
    configure(_test_settings())
    yield
    invalidate_cache()
    await close_admin_pools()
    await close_tenant_pools()


# ── RS256 real (STD-QA-001: sem HS*, sem bypass) ──────────────────────────────
@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint_token(
    rsa_key: rsa.RSAPrivateKey,
    *,
    tenant_id: str | None = TENANT_A,
    aud: str = "mcp:audit-mcp",
    jti: str = "jti-1",
    exp_delta: int = 300,
    include_jti: bool = True,
) -> str:
    """Assina um inner Twin Token RS256 real (aud=mcp:<ns>, jti, exp, tenant_id)."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {"aud": aud, "exp": now + timedelta(seconds=exp_delta), "iat": now}
    if include_jti:
        claims["jti"] = jti
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return jwt.encode(claims, rsa_key, algorithm="RS256")


def patch_jwks(monkeypatch: pytest.MonkeyPatch, rsa_key: rsa.RSAPrivateKey) -> None:
    """Faz o PyJWKClient servir a chave pública local — a verificação RS256 é REAL
    (só evita o fetch de rede do JWKS; nada de bypass)."""
    public_key = rsa_key.public_key()

    class _SigningKey:
        key = public_key

    class _Client:
        def __init__(self, _url: str) -> None:
            pass

        def get_signing_key_from_jwt(self, _token: str) -> _SigningKey:
            return _SigningKey()

    monkeypatch.setattr(jwt, "PyJWKClient", _Client)


# ── Repos temporários + settings herméticos (checkers/policies, sem DB) ───────
@pytest.fixture
def tmp_repo(tmp_path: Path):
    """Cria repo temporário com estrutura básica (para os checkers do run_audit)."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'test'", encoding="utf-8")
    (repo / "README.md").write_text("# Test Repo", encoding="utf-8")
    return repo


@pytest.fixture
def settings() -> AuditSettings:
    """Settings herméticas (apontam para as policies reais do repo)."""
    return _test_settings()
