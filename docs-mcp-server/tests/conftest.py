"""Fixtures da Suíte Canônica do docs-mcp (§16 — PA-01 / FID-02).

**Banco REAL, nunca mockado** (FID-02): os testes do store/tools/servidor que tocam
persistência rodam contra um MySQL 8.x real com **2 tenants** (banco-por-tenant),
exercitando o caminho canônico `get_pool_for_tenant -> Repository -> dialeto MySQL`. O
único "duplo" é o ``platform_lookup`` (linha estática que substitui a consulta ao
admin-mysql PLATFORMS) — a credencial do tenant, não o banco. RS256 é **real** (chave
gerada, token assinado, verificador real) — nunca bypass (STD-QA-001 / Test Doubles
Policy).

As tools compute-only (validação/scan de filesystem/templates) não tocam o banco;
seus testes passam ``store=None`` e permanecem herméticos (sem MySQL).

Config via env (o CI provê o serviço MySQL):
  MYSQL_ROOT_PASSWORD  — senha root (obrigatória; sem ela os testes de DB são SKIPADOS)
  PILOT_MYSQL_HOST     — default 127.0.0.1
  PILOT_MYSQL_PORT     — default 3306
"""

from __future__ import annotations

import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import aiomysql  # noqa: E402
from platform_core.request_context import reset_tenant_id, set_tenant_id  # noqa: E402
from platform_database import close_tenant_pools  # noqa: E402
from platform_database.orm import configure  # noqa: E402
from platform_database.orm.dialects import dialect_for_pool  # noqa: E402
from platform_database.orm.tenant import TenantSession  # noqa: E402
from platform_database.tenant_resolver import get_pool_for_tenant  # noqa: E402

from src.config.settings import DocsSettings  # noqa: E402
from src.db.schema import ensure_schema  # noqa: E402
from src.db.store import DocsStore  # noqa: E402

_HOST = os.environ.get("PILOT_MYSQL_HOST", "127.0.0.1")
_PORT = int(os.environ.get("PILOT_MYSQL_PORT", "3306"))
_PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")

TENANT_A = "docs_test_a"
TENANT_B = "docs_test_b"


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


def _test_settings(**over: Any) -> DocsSettings:
    kw: dict[str, Any] = dict(
        MCP_TWIN_AUDIENCE="mcp:docs-mcp",
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
    return DocsSettings(**kw)


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
async def _make_store(tenant_id: str) -> tuple[DocsStore, Any]:
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
    for table in ("audits", "doc_index"):
        await pool.execute(f"TRUNCATE TABLE {table}")
    token = set_tenant_id(tenant_id)
    return DocsStore(TenantSession(pool, tenant_id)), token


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
                # Banco do tenant PRISTINO por invocação (DROP+CREATE, não IF NOT EXISTS):
                # o E2E credencial-zero afirma contagens absolutas e os fixtures `stores_*`
                # truncam no setup — não no teardown —, então linhas de um teste anterior
                # sobre o mesmo tenant persistiriam e furariam o assert. Recriar o schema é
                # gated por `_SCHEMA_READY.discard(...)` no próprio teste.
                await cur.execute(f"DROP DATABASE IF EXISTS {tid}")
                await cur.execute(f"CREATE DATABASE {tid} CHARACTER SET utf8mb4")
    finally:
        conn.close()

    invalidate_cache()
    configure(_test_settings())
    yield
    invalidate_cache()
    await close_admin_pools()
    await close_tenant_pools()


# ── Fixtures herméticas (tools compute-only + filesystem) ─────────────────────
@pytest.fixture
def settings() -> DocsSettings:
    """Settings puro (sem DB) para as tools compute-only."""
    return DocsSettings(
        stale_days_threshold=90,
        check_external_links=False,
        http_timeout=5.0,
        max_file_size_kb=500,
    )


@pytest.fixture
def tmp_repo(tmp_path):
    """Cria estrutura mínima de repo para testes."""
    readme_content = (
        "# Test Service\n\n## Installation\n\nfoo bar baz qux quux\n\n## Usage\n\nbar baz qux quux corge\n"
    ) * 5
    (tmp_path / "README.md").write_text(readme_content, encoding="utf-8")
    changelog_content = (
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial release\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog_content, encoding="utf-8")
    return tmp_path


# ── RS256 real (STD-QA-001: sem HS*, sem bypass) ──────────────────────────────
@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint_token(
    rsa_key: rsa.RSAPrivateKey,
    *,
    tenant_id: str | None = TENANT_A,
    aud: str = "mcp:docs-mcp",
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
