"""Fixtures da Suíte Canônica do infra-mcp (§16 — PA-01 / FID-02).

**Banco REAL, nunca mockado** (FID-02): os testes do allocator/tools/servidor rodam contra
um MySQL 8.x real com **2 tenants** (banco-por-tenant), exercitando o caminho canônico
``get_pool_for_tenant -> Repository/UnitOfWork -> dialeto MySQL``. O único "duplo" é o
``platform_lookup`` (linha estática que substitui a consulta ao admin-mysql PLATFORMS) —
a credencial do tenant, não o banco. RS256 é **real** (chave gerada, token assinado,
verificador real) — nunca bypass (STD-QA-001 / Test Doubles Policy). O provisioner de
teste é o ``ImmediateProvisioner`` (sem terraform), permitido por ser efeito externo (FID-01).

Config via env (o CI provê o serviço MySQL):
  MYSQL_ROOT_PASSWORD  — senha root (obrigatória; sem ela os testes de DB são SKIPADOS)
  PILOT_MYSQL_HOST     — default 127.0.0.1
  PILOT_MYSQL_PORT     — default 3306

`fake_settings` (Settings com binários inexistentes) é mantido para os testes das tools
compute-only (terraform/checkov/infracost), que não tocam o banco.
"""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
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

from src.config.settings import Settings
from src.db.allocator_store import AllocatorPolicy, AllocatorStore
from src.db.provisioner import ImmediateProvisioner
from src.db.schema import ensure_schema
from src.db.ssh_key import generate_fernet_key

_HOST = os.environ.get("PILOT_MYSQL_HOST", "127.0.0.1")
_PORT = int(os.environ.get("PILOT_MYSQL_PORT", "3306"))
_PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")

TENANT_A = "infra_test_a"
TENANT_B = "infra_test_b"

_ALLOC_TABLES = ("vm_keys", "leases", "queued_requests", "vms")


# ── fake_settings (tools compute-only — sem banco) ────────────────────────────
@pytest.fixture
def fake_settings(tmp_path) -> Settings:
    """Settings que aponta para binários inexistentes (para forçar BinaryNotFound)
    OU para um runner mockado via monkeypatch nos testes específicos."""
    return Settings(
        terraform_root=tmp_path,
        terraform_bin="fake-terraform-bin",
        checkov_bin="fake-checkov-bin",
        infracost_bin="fake-infracost-bin",
        plan_timeout=10,
        validate_timeout=10,
        scan_timeout=10,
        cost_timeout=10,
        output_max_chars=4000,
    )


# ── MySQL real (banco-por-tenant) ─────────────────────────────────────────────
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


def _test_settings(**over: Any) -> Settings:
    kw: dict[str, Any] = dict(
        MCP_TWIN_AUDIENCE="mcp:infra-mcp",
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
    )
    kw.update(over)
    return Settings(**kw)


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


async def _create_db(tenant_id: str) -> None:
    conn = await aiomysql.connect(host=_HOST, port=_PORT, user="root", password=_PW, autocommit=True)
    try:
        async with conn.cursor() as cur:
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {tenant_id} CHARACTER SET utf8mb4")
    finally:
        conn.close()


# Pools aiomysql são atados ao event loop. pytest-asyncio usa um loop por função; a fábrica
# cria os pools no loop do teste e `close_tenant_pools()` no teardown limpa o registry
# (close_all) p/ o próximo teste recriar no seu próprio loop.
@pytest_asyncio.fixture
async def make_store():
    """Fábrica: ``await make_store(tenant_id, policy=?, provisioner=?)`` → AllocatorStore.

    Cria o banco do tenant, garante o schema, TRUNCA as tabelas (estado limpo) e devolve um
    store ligado à ``TenantSession`` do tenant. Reseta o ContextVar e fecha os pools no fim.
    """
    tokens: list[Any] = []
    settings = _test_settings()

    async def _make(
        tenant_id: str,
        policy: AllocatorPolicy | None = None,
        provisioner: Any = None,
    ) -> AllocatorStore:
        await _create_db(tenant_id)
        pool = await get_pool_for_tenant(settings, tenant_id, platform_lookup=_lookup, strict=True)
        await ensure_schema(pool, engine=dialect_for_pool(pool).name)
        for table in _ALLOC_TABLES:
            await pool.execute(f"TRUNCATE TABLE {table}")
        tokens.append(set_tenant_id(tenant_id))
        return AllocatorStore(
            TenantSession(pool, tenant_id),
            provisioner=provisioner or ImmediateProvisioner(),
            policy=policy or AllocatorPolicy(max_cost_usd_per_hour=20.0),
            fernet_key=generate_fernet_key(),
        )

    yield _make

    # O set_tenant_id roda no contexto do teste (quando _make é chamado); este teardown
    # roda no contexto do fixture-fábrica. reset_tenant_id exige o MESMO contexto do set,
    # então cross-contexto levanta ValueError — o ContextVar é task-local (não vaza entre
    # testes), logo o reset é só higiene: ignora quando o contexto difere.
    for token in reversed(tokens):
        try:
            reset_tenant_id(token)
        except ValueError:
            pass
    await close_tenant_pools()


@pytest_asyncio.fixture
async def store_a(make_store):
    return await make_store(TENANT_A)


@pytest_asyncio.fixture
async def store_b(make_store):
    return await make_store(TENANT_B)


@pytest_asyncio.fixture
async def seed_platforms():
    """Semeia ADMIN_DATAFORALL.PLATFORMS no MySQL de teste + ``configure()``.

    Exercita o caminho credencial-zero REAL (``for_tenant`` -> get_platform -> PLATFORMS),
    não o ``platform_lookup`` estático. A tabela é mínima (só as colunas que o resolver lê)."""
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
    aud: str = "mcp:infra-mcp",
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
