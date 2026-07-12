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
    set_credential_secure,
)
from src.tools.env_tool import (
    audit_env_files,
    get_env_config,
    list_environments,
    push_env_to_store,
    read_env_file,
    redact_env_secrets,
    set_env_var,
    sync_env_file,
)
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


# ── Credentials: caminhos extra ─────────────────────────────────────────────────
async def test_set_credential_without_description(store_a):
    res = await set_credential(store_a, "credentials.github", "GITHUB_TOKEN", "ghp_x")
    assert res["success"] is True
    assert "description" not in res


async def test_get_credential_absent(store_a):
    res = await get_credential(store_a, "credentials.acr", "MISSING")
    assert res["found"] is False


async def test_delete_credential_absent(store_a):
    res = await delete_credential(store_a, "credentials.acr", "NOPE")
    assert res["deleted"] is False


async def test_list_credentials_all_namespaces(store_a):
    await set_credential(store_a, "credentials.acr", "ACR_USERNAME", "u")
    await set_credential(store_a, "credentials.github", "GITHUB_TOKEN", "t")
    listed = await list_credentials(store_a)  # namespace=None → todos
    assert listed["total_keys"] == 2
    assert set(listed["namespaces"]) == {"credentials.acr", "credentials.github"}


async def test_set_credential_secure_success(store_a, monkeypatch):
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "topsecret")
    res = await set_credential_secure(store_a, "credentials.e2e", "E2E_USER_PASSWORD")
    assert res["success"] is True
    assert await store_a.get("credentials.e2e", "E2E_USER_PASSWORD") == "topsecret"


async def test_set_credential_secure_empty_value(store_a, monkeypatch):
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    res = await set_credential_secure(store_a, "credentials.e2e", "EMPTY_KEY")
    assert res["success"] is False
    assert "vazio" in res["error"].lower()


async def test_set_credential_secure_cancelled(store_a, monkeypatch):
    import getpass

    def _boom(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr(getpass, "getpass", _boom)
    res = await set_credential_secure(store_a, "credentials.e2e", "CANCEL_KEY")
    assert res["success"] is False
    assert "cancel" in res["error"].lower()


# ── Env: filtros, limite e sync com merge ────────────────────────────────────────
async def test_get_env_config_pattern_and_limit(store_a):
    await set_env_var(store_a, "dev", "DATABASE_URL", "d")
    await set_env_var(store_a, "dev", "DATABASE_POOL", "p")
    await set_env_var(store_a, "dev", "REDIS_URL", "r")

    filtered = await get_env_config(store_a, "dev", key_pattern="database")
    assert set(filtered["config"]) == {"DATABASE_URL", "DATABASE_POOL"}
    assert filtered["count"] == 2

    limited = await get_env_config(store_a, "dev", limit=1)
    assert limited["count"] == 1


async def test_sync_env_file_empty_store(store_a, tmp_path):
    result = await sync_env_file(store_a, str(tmp_path / ".env.void"), "void")
    assert result["success"] is False
    assert "Nenhuma variável" in result["error"]


async def test_sync_env_file_merges_local(store_a, tmp_path):
    await set_env_var(store_a, "dev", "FROM_STORE", "s")
    path = tmp_path / ".env.dev"
    path.write_text("# local header\nLOCAL_ONLY=keepme\nFROM_STORE=old\n", encoding="utf-8")

    result = await sync_env_file(store_a, str(path), "dev", merge=True)
    assert result["success"] is True
    content = path.read_text(encoding="utf-8")
    assert "LOCAL_ONLY=keepme" in content  # var local preservada no merge
    assert "FROM_STORE=s" in content  # store vence a colisão


# ── Env: I/O de disco (read/audit/redact/push) ───────────────────────────────────
async def test_read_env_file_and_filter(store_a, tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nDATABASE_URL=postgres://x\nREDIS_URL=redis://y\n\n", encoding="utf-8")

    full = await read_env_file(store_a, path=str(p))
    assert full["count"] == 2
    assert full["variables"]["DATABASE_URL"] == "postgres://x"

    filtered = await read_env_file(store_a, path=str(p), key_filter="redis")
    assert list(filtered["variables"]) == ["REDIS_URL"]


async def test_read_env_file_missing(store_a, tmp_path):
    res = await read_env_file(store_a, path=str(tmp_path / "absent.env"))
    assert res["error"] == "FileNotFound"


async def test_audit_env_files_flags_secrets_and_non_canonical(store_a, tmp_path):
    (tmp_path / ".env.local-dev").write_text("API_KEY=realhardcoded123\nHOST=localhost\n", encoding="utf-8")
    (tmp_path / ".env.weird").write_text("DB_PASSWORD=plaintextpw\n", encoding="utf-8")
    # secret já coberto no store → in_store True
    await store_a.set("env.local-dev", "API_KEY", "realhardcoded123")

    res = await audit_env_files(store_a, directory=str(tmp_path), check_store=True)
    assert res["hardcoded_secrets_count"] == 2
    assert ".env.weird" in res["non_canonical_files"]
    assert res["summary"]["ok"] is False
    covered = {s["key"]: s["in_store"] for s in res["hardcoded_secrets"]}
    assert covered["API_KEY"] is True
    assert covered["DB_PASSWORD"] is False


async def test_audit_env_files_no_store_check(store_a, tmp_path):
    (tmp_path / ".env.test").write_text("TOKEN_SECRET=abc123def\n", encoding="utf-8")
    res = await audit_env_files(store_a, directory=str(tmp_path), check_store=False)
    assert res["hardcoded_secrets_count"] == 1
    assert res["hardcoded_secrets"][0]["in_store"] is False


async def test_redact_env_secrets_dry_run_then_apply(store_a, tmp_path):
    p = tmp_path / ".env.local-dev"
    original = "# header\nAPI_KEY=supersecretvalue\nSAFE_TOKEN=${SAFE_TOKEN}\nPLAIN=hello\n"
    p.write_text(original, encoding="utf-8")

    dry = await redact_env_secrets(store_a, paths=[str(p)], dry_run=True)
    assert dry["total_changes"] == 1  # só API_KEY (SAFE_TOKEN já é referência; PLAIN não é secret)
    assert p.read_text(encoding="utf-8") == original  # dry-run não escreve

    applied = await redact_env_secrets(store_a, paths=[str(p)], dry_run=False)
    assert applied["total_changes"] == 1
    content = p.read_text(encoding="utf-8")
    assert "API_KEY=${API_KEY}" in content
    assert "PLAIN=hello" in content


async def test_redact_env_secrets_explicit_keys_and_missing(store_a, tmp_path):
    p = tmp_path / ".env.explicit"
    p.write_text("PLAIN_NAME=redactme\n", encoding="utf-8")
    res = await redact_env_secrets(
        store_a, paths=[str(p), str(tmp_path / "ghost.env")], keys=["PLAIN_NAME"], auto_detect=False
    )
    assert res["total_changes"] == 1
    assert any("FileNotFound" in e for e in res["errors"])
    assert "PLAIN_NAME=${PLAIN_NAME}" in p.read_text(encoding="utf-8")


async def test_push_env_to_store_overwrite_and_secrets_only(store_a, tmp_path):
    p = tmp_path / ".env.dev"
    p.write_text("# c\nNEW_VAR=1\nEXISTING=fromfile\nAPI_TOKEN=sekret\n", encoding="utf-8")
    await store_a.set("env.dev", "EXISTING", "already")

    # overwrite=False → EXISTING é pulado; NEW_VAR e API_TOKEN entram.
    res = await push_env_to_store(store_a, path=str(p), environment="dev", overwrite=False)
    assert res["pushed"] == 2
    assert res["skipped"] == 1
    assert await store_a.get("env.dev", "EXISTING") == "already"
    assert await store_a.get("env.dev", "NEW_VAR") == "1"

    # secrets_only=True + overwrite=True → só API_TOKEN é (re)escrito.
    res2 = await push_env_to_store(store_a, path=str(p), environment="dev", overwrite=True, secrets_only=True)
    assert res2["vars"] == ["API_TOKEN"]


async def test_push_env_to_store_missing(store_a, tmp_path):
    res = await push_env_to_store(store_a, path=str(tmp_path / "nope.env"), environment="dev")
    assert res["error"] == "FileNotFound"


# ── Workspace: fallbacks de env, validação de path e chaves extra ───────────────
async def test_workspace_get_key_env_fallback(store_a, monkeypatch):
    monkeypatch.setenv("WORKSPACE_EDITOR", "vim")
    got = await get_workspace_config(store_a, key="EDITOR")
    assert got["value"] == "vim"
    assert got["source"] == "env_fallback"


async def test_workspace_get_repos_root_env_fallback(store_a, monkeypatch):
    monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
    monkeypatch.setenv("DEPLOY_REPOS_ROOT", "/srv/repos")
    got = await get_workspace_config(store_a, key="REPOS_ROOT")
    assert got["value"] == "/srv/repos"


async def test_workspace_get_all_with_env_repos_root(store_a, monkeypatch):
    monkeypatch.delenv("REPOS_ROOT", raising=False)
    monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
    monkeypatch.setenv("DEPLOY_REPOS_ROOT", "/srv/repos")
    await store_a.set("workspace", "PYTHON_BIN", "python3.12")
    res = await get_workspace_config(store_a)  # sem key → todas
    assert res["config"]["PYTHON_BIN"] == {"value": "python3.12", "source": "store"}
    assert res["config"]["REPOS_ROOT"] == {"value": "/srv/repos", "source": "env"}


async def test_workspace_set_repos_root_validation_error(store_a, tmp_path):
    missing = str(tmp_path / "does-not-exist")
    res = await set_workspace_config(store_a, key="REPOS_ROOT", value=missing, create_dir=False)
    assert "error" in res
    assert "create_dir" in res["tip"]


async def test_workspace_set_repos_root_existing_dir(store_a, tmp_path):
    # Caminho já existente (diretório) → set_workspace_config só valida quando NÃO existe,
    # então grava direto (branch p.exists() → pula a validação).
    res = await set_workspace_config(store_a, key="REPOS_ROOT", value=str(tmp_path), create_dir=False)
    assert res["action"] == "set"
    assert res["key"] == "REPOS_ROOT"
    assert await store_a.get("workspace", "REPOS_ROOT") == str(tmp_path)


async def test_workspace_set_repos_root_create_dir(store_a, tmp_path):
    target = tmp_path / "new-repos"
    res = await set_workspace_config(store_a, key="REPOS_ROOT", value=str(target), create_dir=True)
    assert res["action"] == "set"
    assert target.is_dir()
    assert await store_a.get("workspace", "REPOS_ROOT") == str(target)


async def test_workspace_list_includes_extra_key(store_a):
    await store_a.set("workspace", "CUSTOM_KEY", "custom")
    listed = await list_workspace_config(store_a)
    rows = {r["key"]: r for r in listed["config"]}
    assert rows["CUSTOM_KEY"]["canonical"] is False
    assert rows["CUSTOM_KEY"]["value"] == "custom"
    # chaves canônicas não setadas aparecem em missing_canonical
    assert "REPOS_ROOT" in listed["missing_canonical"]
    assert listed["setup_tip"] is not None


# ── Tenants: não encontrado, filtro e limite ─────────────────────────────────────
async def test_get_tenant_config_not_found(store_a):
    res = await get_tenant_config(store_a, "tenant_ghost")
    assert res["found"] is False


async def test_get_tenant_config_pattern_and_limit(store_a):
    await set_tenant_config(store_a, "t1", "DATABASE_URL", "d")
    await set_tenant_config(store_a, "t1", "DATABASE_POOL", "p")
    await set_tenant_config(store_a, "t1", "REDIS_URL", "r")

    filtered = await get_tenant_config(store_a, "t1", key_pattern="database")
    assert set(filtered["config"]) == {"DATABASE_URL", "DATABASE_POOL"}

    limited = await get_tenant_config(store_a, "t1", limit=1)
    assert limited["count"] == 1
