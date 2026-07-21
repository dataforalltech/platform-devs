"""Testes de integração da jornada project-scoped no domain `session` consolidado.

Banco REAL, credencial-zero (mesma política FID-02 do standalone): rodam contra um MySQL
real via ``get_pool_for_tenant`` e são SKIPADOS sem ``MYSQL_ROOT_PASSWORD``. Cobrem a
Fatia A2/A3 do ADR-017 (sessão project-scoped + session_bootstrap + backfill idempotente).
"""

from __future__ import annotations

import os
import socket
from typing import Any

import aiomysql
import pytest
import pytest_asyncio
from platform_core.request_context import reset_tenant_id, set_tenant_id
from platform_database import close_tenant_pools
from platform_database.orm import configure
from platform_database.orm.dialects import dialect_for_pool
from platform_database.orm.tenant import TenantSession
from platform_database.tenant_resolver import get_pool_for_tenant

from src.config.settings import DevteamSettings
from src.domains.session.catalog import dispatch
from src.domains.session.db.schema import ensure_schema
from src.domains.session.db.store import SessionStore
from src.domains.session.tools.session_tool import session_bootstrap, start_session

_HOST = os.environ.get("PILOT_MYSQL_HOST", "127.0.0.1")
_PORT = int(os.environ.get("PILOT_MYSQL_PORT", "3306"))
_PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")
_TENANT = "devteam_session_journey_test"
_ALL_TABLES = (
    "decisions", "suggestions", "session_services", "tasks", "artifacts", "checkpoints", "sessions",
)
_configured = False


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


def _settings() -> DevteamSettings:
    return DevteamSettings(
        MCP_TWIN_AUDIENCE="mcp:devteam-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        DB_ENGINE="mysql", DB_HOST=_HOST, DB_PORT=_PORT, DB_USER="root", DB_PASSWORD=_PW,
        ADMIN_DB_HOST=_HOST, ADMIN_DB_PORT=_PORT, ADMIN_DB_USER="root", ADMIN_DB_PASSWORD=_PW,
    )


async def _lookup(tenant_id: str, _s: Any) -> dict[str, Any] | None:
    if tenant_id != _TENANT:
        return None
    return {
        "tenant_id": tenant_id, "db_engine": "mysql", "db_host": _HOST, "db_port": _PORT,
        "db_name": tenant_id, "db_user": "root", "db_password": _PW,
    }


async def _root_exec(sql: str) -> None:
    conn = await aiomysql.connect(host=_HOST, port=_PORT, user="root", password=_PW, autocommit=True)
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql)
    finally:
        conn.close()


async def _make_store() -> tuple[SessionStore, Any]:
    global _configured
    settings = _settings()
    if not _configured:
        configure(settings)
        _configured = True
    await _root_exec(f"CREATE DATABASE IF NOT EXISTS {_TENANT} CHARACTER SET utf8mb4")
    pool = await get_pool_for_tenant(settings, _TENANT, platform_lookup=_lookup, strict=True)
    await ensure_schema(pool, engine=dialect_for_pool(pool).name)
    for table in _ALL_TABLES:
        await pool.execute(f"TRUNCATE TABLE {table}")
    token = set_tenant_id(_TENANT)
    return SessionStore(TenantSession(pool, _TENANT)), token


@pytest_asyncio.fixture
async def store():
    st, token = await _make_store()
    yield st
    reset_tenant_id(token)
    await close_tenant_pools()


@requires_mysql
@pytest.mark.asyncio
async def test_create_session_project_scoped_persists_new_fields(store: SessionStore) -> None:
    sess = await store.create_session(
        title="J", objective="O", project_id="proj-123", agent_client="claude-code",
        environment={"os": "linux", "agent_client": {"name": "claude-code", "version": "1.2"}},
    )
    got = await store.get_session(sess["id"])
    assert got is not None
    assert got["project_id"] == "proj-123"
    assert got["agent_client"] == "claude-code"
    assert got["environment_json"] and "linux" in got["environment_json"]
    assert got["repo"] is None


@requires_mysql
@pytest.mark.asyncio
async def test_start_session_requires_repo_or_project(store: SessionStore) -> None:
    out = await start_session(store, "develop", title="T", objective="O")
    assert out.get("error") == "ValidationError"


@requires_mysql
@pytest.mark.asyncio
async def test_start_session_repo_scoped_still_returns_branch(store: SessionStore) -> None:
    out = await start_session(store, "develop", title="T", objective="O", repo="platform-devs")
    assert out.get("error") is None
    assert out.get("branch")  # repo-scoped mantém o comportamento de branch/next_action
    assert out.get("next_action")


@requires_mysql
@pytest.mark.asyncio
async def test_session_bootstrap_creates_project_scoped_session(store: SessionStore) -> None:
    boot = await session_bootstrap(
        store, "develop", project_id="proj-999", agent_client="codex", environment={"os": "mac"}
    )
    assert boot["project_id"] == "proj-999"
    assert boot["credential_status"] == "deferred"
    assert boot["workspace_status"] == "deferred"
    assert boot["environment_captured"] is True
    persisted = await store.get_session(boot["session_id"])
    assert persisted is not None
    assert persisted["project_id"] == "proj-999"
    assert persisted["agent_client"] == "codex"


@requires_mysql
@pytest.mark.asyncio
async def test_session_bootstrap_dispatches_via_catalog(store: SessionStore) -> None:
    result = await dispatch(
        "session_bootstrap", {"project_id": "proj-cat", "agent_client": "claude-code"}, store
    )
    assert result["project_id"] == "proj-cat"
    assert result["credential_status"] == "deferred"


@requires_mysql
@pytest.mark.asyncio
async def test_ensure_schema_backfills_columns_on_existing_tenant() -> None:
    store, token = await _make_store()
    try:
        # Simula um tenant PRÉ-EXISTENTE que não tem as colunas novas.
        await _root_exec(f"ALTER TABLE {_TENANT}.sessions DROP COLUMN project_id")
        await _root_exec(f"ALTER TABLE {_TENANT}.sessions DROP COLUMN environment_json")
        pool = await get_pool_for_tenant(_settings(), _TENANT, platform_lookup=_lookup)
        await ensure_schema(pool, engine=dialect_for_pool(pool).name)  # backfill idempotente
        sess = await store.create_session(title="M", objective="O", project_id="after-backfill")
        got = await store.get_session(sess["id"])
        assert got is not None
        assert got["project_id"] == "after-backfill"
    finally:
        reset_tenant_id(token)
        await close_tenant_pools()
