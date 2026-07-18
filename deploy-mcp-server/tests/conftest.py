"""Fixtures compartilhadas para todos os testes do deploy-mcp-server.

Duas famílias:

1. **Compute/GitHub (mockado, FID-01)** — o GitHubClient é mockado (MagicMock ou
   ``Github`` patchado). Nenhuma chamada real de rede. Fixtures: ``settings``,
   ``mock_github``, ``client`` + helpers ``make_mock_*``.

2. **Ledger (MySQL REAL, FID-02)** — o ledger persistido roda contra um MySQL 8.x real
   com **2 tenants** (banco-por-tenant), exercitando o caminho canônico
   ``get_pool_for_tenant -> Repository -> dialeto MySQL``. RS256 é **real**
   (``mint_token``/``patch_jwks``, nunca bypass). O único "duplo" do caminho de DB é o
   ``platform_lookup`` estático (a credencial do tenant, não o banco).

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
from unittest.mock import MagicMock, patch

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

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config.settings import DeploySettings  # noqa: E402
from src.db.schema import (  # noqa: E402
    BRANCHES_TABLE,
    DEPLOYMENTS_TABLE,
    EVENTS_TABLE,
    PULL_REQUESTS_TABLE,
    REPOS_TABLE,
    WORKFLOW_RUNS_TABLE,
    ensure_schema,
)
from src.db.store import DeployStore  # noqa: E402
from src.knowledge.github_client import GitHubClient  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# Compute/GitHub (mockado)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def settings() -> DeploySettings:
    return DeploySettings(
        github_token="test_token_ghp_xxx",
        github_org="test-org",
        acr_registry="test.azurecr.io",
        acr_namespace="test/3.0",
        default_base_branch="develop",
    )


@pytest.fixture
def mock_github():
    """Patch Github() para evitar chamadas reais à API."""
    with patch("src.knowledge.github_client.Github") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def client(settings, mock_github) -> GitHubClient:
    """GitHubClient com Github mockado."""
    return GitHubClient(settings)


def make_mock_repo(
    name: str = "my-repo",
    default_branch: str = "develop",
    private: bool = True,
) -> MagicMock:
    repo = MagicMock()
    repo.name = name
    repo.full_name = f"test-org/{name}"
    repo.default_branch = default_branch
    repo.private = private
    repo.archived = False
    repo.html_url = f"https://github.com/test-org/{name}"
    return repo


def make_mock_pr(
    number: int = 42,
    title: str = "feat: test",
    state: str = "open",
    head_ref: str = "feature/test",
    base_ref: str = "develop",
    head_sha: str = "abc1234",
    draft: bool = False,
) -> MagicMock:
    pr = MagicMock()
    pr.number = number
    pr.title = title
    pr.state = state
    pr.html_url = f"https://github.com/test-org/my-repo/pull/{number}"
    pr.head.ref = head_ref
    pr.head.sha = head_sha
    pr.base.ref = base_ref
    pr.mergeable = True
    pr.mergeable_state = "clean"
    pr.draft = draft
    pr.user.login = "test-user"
    return pr


def make_mock_run(
    run_id: int = 12345,
    name: str = "CD DEV",
    status: str = "completed",
    conclusion: str = "success",
    head_branch: str = "develop",
    head_sha: str = "abc1234",
) -> MagicMock:
    from datetime import datetime as _dt

    run = MagicMock()
    run.id = run_id
    run.name = name
    run.status = status
    run.conclusion = conclusion
    run.head_branch = head_branch
    run.head_sha = head_sha
    run.created_at = _dt(2026, 5, 7, 10, 0, 0)
    run.updated_at = _dt(2026, 5, 7, 10, 5, 0)
    run.html_url = f"https://github.com/test-org/my-repo/actions/runs/{run_id}"
    run.logs_url = f"https://api.github.com/repos/test-org/my-repo/actions/runs/{run_id}/logs"
    return run


# ══════════════════════════════════════════════════════════════════════════════
# FakeGitHubClient — duplo do backend externo (FID-01): retorna dicts realistas
# (mesma forma que o GitHubClient real), para o ledger persistir a row certa.
# ══════════════════════════════════════════════════════════════════════════════
class FakeGitHubClient:
    """Duplo do GitHubClient: as ações "acontecem" e devolvem o mesmo shape do real."""

    def __init__(self, settings: DeploySettings) -> None:
        self._settings = settings

    def list_repos(self, org=None, filter_name=None, include_archived=False):
        return [
            {
                "name": "svc",
                "full_name": "org/svc",
                "default_branch": "develop",
                "visibility": "private",
                "archived": False,
                "url": "https://github.com/org/svc",
            }
        ]

    def create_branch(self, repo, branch, from_ref):
        return {"branch": branch, "sha": "abc1234def", "repo": repo}

    def list_branches(self, repo, filter_name=None):
        return [{"name": "develop", "sha": "abc123", "protected": True}]

    def commit_files(self, repo, branch, message, files, author_name=None, author_email=None):
        return {
            "sha": "deadbeef7",
            "url": "https://github.com/commit/deadbeef7",
            "files": [f["path"] for f in files],
        }

    def create_pr(self, repo, title, body, head, base, labels=None, reviewers=None, draft=False):
        return {
            "number": 7,
            "title": title,
            "state": "open",
            "url": f"https://github.com/{repo}/pull/7",
            "head": head,
            "base": base,
            "head_sha": "abc123",
            "mergeable": True,
            "mergeable_state": "clean",
            "draft": draft,
        }

    def get_pr(self, repo, pr_number):
        return {
            "number": pr_number,
            "title": "feat: refreshed",
            "state": "open",
            "url": f"https://github.com/{repo}/pull/{pr_number}",
            "head": "feature/x",
            "base": "develop",
            "head_sha": "abc123",
            "mergeable": True,
            "mergeable_state": "clean",
            "draft": False,
            "checks": [],
        }

    def merge_pr(self, repo, pr_number, method="squash", commit_title=None, commit_message=None):
        return {"merged": True, "sha": "mergedsha7", "message": "Pull Request successfully merged"}

    def list_prs(self, repo, state="open", base=None, author=None):
        return [
            {
                "number": 7,
                "title": "feat",
                "state": state,
                "url": "u",
                "head": "h",
                "base": "develop",
                "head_sha": "abc",
            }
        ]

    def list_acr_tags(self, registry, namespace, service_name, username, password, limit=20):
        return [{"name": "v1", "digest": "d", "created_at": "", "last_update": ""}]


# ══════════════════════════════════════════════════════════════════════════════
# Ledger (MySQL real)
# ══════════════════════════════════════════════════════════════════════════════
_HOST = os.environ.get("PILOT_MYSQL_HOST", "127.0.0.1")
_PORT = int(os.environ.get("PILOT_MYSQL_PORT", "3306"))
_PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")

TENANT_A = "deploy_mcp_test_a"
TENANT_B = "deploy_mcp_test_b"

# Todas as tabelas do ledger (ordem estável p/ TRUNCATE no setup dos fixtures).
_TABLES = (
    DEPLOYMENTS_TABLE,
    PULL_REQUESTS_TABLE,
    BRANCHES_TABLE,
    WORKFLOW_RUNS_TABLE,
    REPOS_TABLE,
    EVENTS_TABLE,
)


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


def _test_settings(**over: Any) -> DeploySettings:
    kw: dict[str, Any] = dict(
        github_token="test_token_ghp_xxx",
        github_org="test-org",
        acr_username="acr-user",
        acr_password="acr-pass",
        MCP_TWIN_AUDIENCE="mcp:deploy-mcp",
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
    return DeploySettings(**kw)


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
async def _make_store(tenant_id: str) -> tuple[DeployStore, Any]:
    settings = _test_settings()
    conn = await aiomysql.connect(host=_HOST, port=_PORT, user="root", password=_PW, autocommit=True)
    try:
        async with conn.cursor() as cur:
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS {tenant_id} CHARACTER SET utf8mb4")
    finally:
        conn.close()
    pool = await get_pool_for_tenant(settings, tenant_id, platform_lookup=_lookup, strict=True)
    await ensure_schema(pool, engine=dialect_for_pool(pool).name)
    for table in _TABLES:
        await pool.execute(f"TRUNCATE TABLE {table}")
    token = set_tenant_id(tenant_id)
    return DeployStore(TenantSession(pool, tenant_id)), token


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
    não o platform_lookup estático. O banco do tenant é PRISTINO por invocação
    (DROP+CREATE): o E2E afirma contagens absolutas e o schema é recriado no próprio
    teste via `_SCHEMA_READY.discard(...)`."""
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


# ── RS256 real (STD-QA-001: sem HS*, sem bypass) ──────────────────────────────
@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint_token(
    rsa_key: rsa.RSAPrivateKey,
    *,
    tenant_id: str | None = TENANT_A,
    aud: str = "mcp:deploy-mcp",
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
