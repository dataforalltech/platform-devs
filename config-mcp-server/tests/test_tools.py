"""Camada de tools (async) sobre o ConfigStore real (§16 / FID-02).

Exercita credenciais/env/workspace/tenants pelo caminho canônico
(tool async -> ConfigStore -> Repository -> MySQL), com encriptação Fernet real.
"""

from __future__ import annotations

import pytest

from src.tools.credential_tool import (
    delete_credential,
    get_credential,
    list_credentials,
    set_credential,
)
from src.tools.env_tool import get_env_config, list_environments, set_env_var, sync_env_file
from src.tools.tenant_tool import (
    get_session_tenant_config,
    get_tenant_config,
    list_tenants,
    set_tenant_config,
)
from src.tools.workspace_tool import (
    get_workspace_config,
    list_workspace_config,
    set_workspace_config,
)

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Credentials ────────────────────────────────────────────────────────────────
async def test_credential_set_get_list_delete(store_a):
    await set_credential(store_a, "credentials.acr", "ACR_USERNAME", "user123", description="doc")
    got = await get_credential(store_a, "credentials.acr", "ACR_USERNAME")
    assert got["found"] is True
    assert got["value"] == "user123"

    listed = await list_credentials(store_a, "credentials.acr")
    assert "ACR_USERNAME" in listed["namespaces"]["credentials.acr"]
    assert listed["total_keys"] == 1

    deleted = await delete_credential(store_a, "credentials.acr", "ACR_USERNAME")
    assert deleted["deleted"] is True
    assert (await get_credential(store_a, "credentials.acr", "ACR_USERNAME"))["found"] is False


# ── Env ────────────────────────────────────────────────────────────────────────
async def test_env_set_get_and_list(store_a):
    await set_env_var(store_a, "dev", "DATABASE_URL", "postgres://localhost/db")
    cfg = await get_env_config(store_a, "dev")
    assert cfg["config"]["DATABASE_URL"] == "postgres://localhost/db"

    await set_env_var(store_a, "production", "B", "2")
    envs = await list_environments(store_a)
    assert set(envs["environments"]) == {"dev", "production"}


async def test_sync_env_file_writes_store_values(store_a, tmp_path):
    await set_env_var(store_a, "dev", "DATABASE_URL", "postgres://localhost/db")
    await set_env_var(store_a, "dev", "REDIS_URL", "redis://localhost")
    path = str(tmp_path / ".env.dev")
    result = await sync_env_file(store_a, path, "dev")
    assert result["success"] is True
    content = (tmp_path / ".env.dev").read_text(encoding="utf-8")
    assert "DATABASE_URL=postgres://localhost/db" in content
    assert "REDIS_URL=redis://localhost" in content


# ── Workspace ──────────────────────────────────────────────────────────────────
async def test_workspace_set_get_list(store_a):
    await set_workspace_config(store_a, key="PYTHON_BIN", value="python3.12")
    got = await get_workspace_config(store_a, key="PYTHON_BIN")
    assert got["found"] is True
    assert got["value"] == "python3.12"
    assert got["source"] == "store"

    listed = await list_workspace_config(store_a)
    rows = {r["key"]: r for r in listed["config"]}
    assert rows["PYTHON_BIN"]["set"] is True


# ── Tenants (o store JÁ é o banco do tenant; o namespace embute o id) ──────────
async def test_tenant_set_get_and_list(store_a):
    await set_tenant_config(store_a, "tenant_abc", "DATABASE_URL", "postgres://localhost/abc")
    got = await get_tenant_config(store_a, "tenant_abc")
    assert got["found"] is True
    assert got["config"]["DATABASE_URL"] == "postgres://localhost/abc"

    await set_tenant_config(store_a, "tenant_x", "K", "V")
    listed = await list_tenants(store_a)
    assert set(listed["tenants"]) == {"tenant_abc", "tenant_x"}


async def test_session_tenant_config_no_twin(store_a, monkeypatch):
    import src.tools.tenant_tool as tt

    monkeypatch.setattr(tt, "_get_twin_tenant_id", lambda: None)
    result = await get_session_tenant_config(store_a)
    assert result["found"] is False
    assert result["error"] == "no_tenant_in_session"


async def test_session_tenant_config_resolves_from_twin(store_a, monkeypatch):
    import src.tools.tenant_tool as tt

    await set_tenant_config(store_a, "tenant_session_01", "DB_URL", "postgres://session/db")
    monkeypatch.setattr(tt, "_get_twin_tenant_id", lambda: "tenant_session_01")
    result = await get_session_tenant_config(store_a)
    assert result["found"] is True
    assert result["tenant_id"] == "tenant_session_01"
    assert result["config"]["DB_URL"] == "postgres://session/db"
