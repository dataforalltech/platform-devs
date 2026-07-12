"""Gestão de arquivos .env: read/set/sync/audit/redact.

read/set/redact são herméticos (`store=None`); sync/audit usam o registry (MySQL real).
"""

from __future__ import annotations

import pytest

from src.tools.env_tool import (
    audit_env_files,
    read_env_file,
    redact_env_secrets,
    set_env_var,
    sync_service_urls,
)
from src.tools.registry_tool import register_service

from .conftest import requires_mysql


# ── read_env_file (hermético) ─────────────────────────────────────────────────
async def test_read_env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nURL_ADMIN=http://localhost:8000\nDB_PORT=3306\n\n", encoding="utf-8")
    result = await read_env_file(None, path=str(p))
    assert result["count"] == 2
    assert result["variables"]["URL_ADMIN"] == "http://localhost:8000"


async def test_read_env_file_filter(tmp_path):
    p = tmp_path / ".env"
    p.write_text("URL_ADMIN=a\nDB_PORT=3306\n", encoding="utf-8")
    result = await read_env_file(None, path=str(p), key_filter="url")
    assert list(result["variables"]) == ["URL_ADMIN"]


async def test_read_env_file_missing(tmp_path):
    result = await read_env_file(None, path=str(tmp_path / "nope.env"))
    assert result["error"] == "FileNotFound"


# ── set_env_var (hermético) ───────────────────────────────────────────────────
async def test_set_env_var_update(tmp_path):
    p = tmp_path / ".env"
    p.write_text("URL_ADMIN=old\nDB_PORT=3306\n", encoding="utf-8")
    result = await set_env_var(None, path=str(p), key="URL_ADMIN", value="new")
    assert result["action"] == "updated"
    assert result["old_value"] == "old"
    assert "URL_ADMIN=new" in p.read_text(encoding="utf-8")


async def test_set_env_var_create_appends(tmp_path):
    p = tmp_path / ".env"
    p.write_text("URL_ADMIN=a\n", encoding="utf-8")
    result = await set_env_var(None, path=str(p), key="NEW_VAR", value="v", comment="a nova var")
    assert result["action"] == "created"
    content = p.read_text(encoding="utf-8")
    assert "NEW_VAR=v" in content
    assert "# a nova var" in content


async def test_set_env_var_creates_file(tmp_path):
    p = tmp_path / "sub" / ".env"
    result = await set_env_var(None, path=str(p), key="K", value="v")
    assert result["action"] == "created"
    assert p.exists()


async def test_set_env_var_missing_no_create(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=1\n", encoding="utf-8")
    result = await set_env_var(None, path=str(p), key="B", value="2", create_if_missing=False)
    assert result["error"] == "KeyNotFound"


async def test_set_env_var_file_missing_no_create(tmp_path):
    result = await set_env_var(
        None, path=str(tmp_path / "nope.env"), key="K", value="v", create_if_missing=False
    )
    assert result["error"] == "FileNotFound"


# ── redact_env_secrets (hermético) ────────────────────────────────────────────
async def test_redact_auto_detect(tmp_path):
    p = tmp_path / ".env"
    p.write_text("DB_PASSWORD=toor\nPORT=8080\n", encoding="utf-8")
    result = await redact_env_secrets(None, paths=[str(p)])
    assert result["total_changes"] == 1
    assert "DB_PASSWORD=${DB_PASSWORD}" in p.read_text(encoding="utf-8")
    assert "PORT=8080" in p.read_text(encoding="utf-8")


async def test_redact_dry_run(tmp_path):
    p = tmp_path / ".env"
    p.write_text("API_KEY=secret123\n", encoding="utf-8")
    result = await redact_env_secrets(None, paths=[str(p)], dry_run=True)
    assert result["total_changes"] == 1
    assert "API_KEY=secret123" in p.read_text(encoding="utf-8")  # não alterado


async def test_redact_explicit_keys(tmp_path):
    p = tmp_path / ".env"
    p.write_text("PLAIN=value\n", encoding="utf-8")
    result = await redact_env_secrets(None, paths=[str(p)], keys=["PLAIN"], auto_detect=False)
    assert result["total_changes"] == 1
    assert "PLAIN=${PLAIN}" in p.read_text(encoding="utf-8")


async def test_redact_skips_safe_and_refs(tmp_path):
    p = tmp_path / ".env"
    p.write_text("DB_PASSWORD=${DB_PASSWORD}\nJWT_SECRET=\n", encoding="utf-8")
    result = await redact_env_secrets(None, paths=[str(p)])
    assert result["total_changes"] == 0


async def test_redact_file_not_found(tmp_path):
    result = await redact_env_secrets(None, paths=[str(tmp_path / "nope.env")])
    assert result["errors"][0]["error"] == "FileNotFound"


# ── sync_service_urls (MySQL real) ────────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_sync_service_urls_changes(store_a, tmp_path):
    await register_service(store_a, name="platform-admin", port=8000, host="localhost")
    p = tmp_path / ".env"
    p.write_text("URL_ADMIN=http://old:1/api/v1\nURL_GHOST=http://x:2\n", encoding="utf-8")
    result = await sync_service_urls(store_a, path=str(p))
    assert result["total_changes"] == 1
    change = result["changes"][0]
    assert change["key"] == "URL_ADMIN"
    assert change["new"] == "http://localhost:8000/api/v1"  # path preservado
    assert "URL_GHOST" in result["not_found_in_registry"]
    assert "URL_ADMIN=http://localhost:8000/api/v1" in p.read_text(encoding="utf-8")


@pytest.mark.integration
@requires_mysql
async def test_sync_service_urls_dry_run(store_a, tmp_path):
    await register_service(store_a, name="platform-admin", port=8000, host="localhost")
    p = tmp_path / ".env"
    p.write_text("URL_ADMIN=http://old:1\n", encoding="utf-8")
    result = await sync_service_urls(store_a, path=str(p), dry_run=True)
    assert result["total_changes"] == 1
    assert "http://old:1" in p.read_text(encoding="utf-8")  # não escreveu


@pytest.mark.integration
@requires_mysql
async def test_sync_service_urls_file_missing(store_a, tmp_path):
    result = await sync_service_urls(store_a, path=str(tmp_path / "nope.env"))
    assert result["error"] == "FileNotFound"


# ── audit_env_files (MySQL real) ──────────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_audit_env_files(store_a, tmp_path):
    await register_service(store_a, name="platform-admin", port=8000, host="localhost")
    (tmp_path / ".env.local-dev").write_text(
        "JWT_SECRET_KEY=abcdef123456\nURL_ADMIN=http://wrong:1\n", encoding="utf-8"
    )
    (tmp_path / ".env.weird").write_text("FOO=bar\n", encoding="utf-8")
    result = await audit_env_files(store_a, directory=str(tmp_path))
    assert result["hardcoded_secrets_count"] == 1
    assert result["hardcoded_secrets"][0]["key"] == "JWT_SECRET_KEY"
    assert result["url_issues_count"] >= 1
    assert ".env.weird" in result["non_canonical_files"]


@pytest.mark.integration
@requires_mysql
async def test_audit_env_dir_missing(store_a, tmp_path):
    result = await audit_env_files(store_a, directory=str(tmp_path / "nope"))
    assert result["error"] == "DirectoryNotFound"


@pytest.mark.integration
@requires_mysql
async def test_audit_env_no_files(store_a, tmp_path):
    result = await audit_env_files(store_a, directory=str(tmp_path))
    assert result["error"] == "NoEnvFilesFound"
