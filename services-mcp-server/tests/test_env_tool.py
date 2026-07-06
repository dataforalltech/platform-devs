"""Testes das tools de gestão de arquivos .env.

Herméticos: usam arquivos temporários (tmp_path), sem rede nem banco.
"""

from __future__ import annotations

from src.tools.env_tool import (
    _extract_url_path,
    _is_safe_value,
    _is_secret_key,
    audit_env_files,
    read_env_file,
    redact_env_secrets,
    set_env_var,
    sync_service_urls,
)

from .conftest import make_service

# ── helpers puros ─────────────────────────────────────────────────────────── #


def test_extract_url_path():
    assert _extract_url_path("http://localhost:8000/api/v1") == "/api/v1"
    assert _extract_url_path("http://localhost:8000") == ""


def test_is_secret_key():
    assert _is_secret_key("JWT_SECRET_KEY")
    assert _is_secret_key("DB_PASSWORD")
    assert _is_secret_key("INTERNAL_API_TOKEN")
    assert not _is_secret_key("TOKEN_EXPIRE_MINUTES")
    assert not _is_secret_key("SERVICE_NAME")


def test_is_safe_value():
    assert _is_safe_value("")
    assert _is_safe_value("${JWT_SECRET_KEY}")
    assert _is_safe_value("changeme")
    assert not _is_safe_value("XrDsC9realsecret")


# ── read_env_file ─────────────────────────────────────────────────────────── #


def test_read_env_file_not_found(store):
    result = read_env_file(store, path="/no/such/file.env")
    assert result["error"] == "FileNotFound"


def test_read_env_file_parses_vars(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nA=1\nB=two\n\nC=3\n", encoding="utf-8")
    result = read_env_file(store, path=str(env))
    assert result["count"] == 3
    assert result["variables"]["A"] == "1"
    assert result["variables"]["B"] == "two"


def test_read_env_file_key_filter(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("URL_ADMIN=x\nDB_HOST=y\nURL_AUTH=z\n", encoding="utf-8")
    result = read_env_file(store, path=str(env), key_filter="url")
    assert set(result["variables"].keys()) == {"URL_ADMIN", "URL_AUTH"}


# ── set_env_var ───────────────────────────────────────────────────────────── #


def test_set_env_var_updates_existing(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nB=2\n", encoding="utf-8")
    result = set_env_var(store, path=str(env), key="A", value="99")
    assert result["action"] == "updated"
    assert result["old_value"] == "1"
    assert "A=99" in env.read_text(encoding="utf-8")


def test_set_env_var_creates_new(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    result = set_env_var(store, path=str(env), key="NEW", value="x", comment="my var")
    assert result["action"] == "created"
    content = env.read_text(encoding="utf-8")
    assert "NEW=x" in content
    assert "# my var" in content


def test_set_env_var_creates_file_when_missing(store, tmp_path):
    env = tmp_path / "sub" / ".env"
    result = set_env_var(store, path=str(env), key="A", value="1", create_if_missing=True)
    assert result["action"] == "created"
    assert env.exists()


def test_set_env_var_missing_file_no_create(store, tmp_path):
    env = tmp_path / ".env"
    result = set_env_var(store, path=str(env), key="A", value="1", create_if_missing=False)
    assert result["error"] == "FileNotFound"


def test_set_env_var_key_not_found_no_create(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    result = set_env_var(store, path=str(env), key="B", value="2", create_if_missing=False)
    assert result["error"] == "KeyNotFound"


# ── sync_service_urls ─────────────────────────────────────────────────────── #


def test_sync_service_urls_file_not_found(store):
    result = sync_service_urls(store, path="/no/such/file.env")
    assert result["error"] == "FileNotFound"


def test_sync_service_urls_updates_from_registry(store, tmp_path):
    make_service(store, name="platform-admin", port=9000)
    env = tmp_path / ".env"
    env.write_text("URL_ADMIN=http://old:1/api\n", encoding="utf-8")

    result = sync_service_urls(store, path=str(env))
    assert result["total_changes"] == 1
    change = result["changes"][0]
    assert change["key"] == "URL_ADMIN"
    # preserva o path /api existente
    assert change["new"] == "http://localhost:9000/api"
    assert "URL_ADMIN=http://localhost:9000/api" in env.read_text(encoding="utf-8")


def test_sync_service_urls_explicit_map(store, tmp_path):
    make_service(store, name="admin", port=7000)
    env = tmp_path / ".env"
    env.write_text("URL_ADMIN=http://old:1\n", encoding="utf-8")
    result = sync_service_urls(
        store, path=str(env), url_map={"URL_ADMIN": "admin"}, url_suffix="/v2"
    )
    assert result["changes"][0]["new"] == "http://localhost:7000/v2"


def test_sync_service_urls_not_found(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("URL_GHOST=http://old:1\n", encoding="utf-8")
    result = sync_service_urls(store, path=str(env))
    assert "URL_GHOST" in result["not_found_in_registry"]


def test_sync_service_urls_dry_run(store, tmp_path):
    make_service(store, name="platform-admin", port=9000)
    env = tmp_path / ".env"
    original = "URL_ADMIN=http://old:1/api\n"
    env.write_text(original, encoding="utf-8")
    result = sync_service_urls(store, path=str(env), dry_run=True)
    assert result["dry_run"] is True
    assert result["changes"]
    assert env.read_text(encoding="utf-8") == original


# ── audit_env_files ───────────────────────────────────────────────────────── #


def test_audit_dir_not_found(store):
    result = audit_env_files(store, directory="/no/such/dir")
    assert result["error"] == "DirectoryNotFound"


def test_audit_no_env_files(store, tmp_path):
    result = audit_env_files(store, directory=str(tmp_path))
    assert result["error"] == "NoEnvFilesFound"


def test_audit_detects_hardcoded_secret(store, tmp_path):
    (tmp_path / ".env.local-dev").write_text(
        "JWT_SECRET_KEY=XrDsC9superSecretValue\nA=1\n", encoding="utf-8"
    )
    result = audit_env_files(store, directory=str(tmp_path), check_registry_urls=False)
    assert result["hardcoded_secrets_count"] == 1
    assert result["hardcoded_secrets"][0]["key"] == "JWT_SECRET_KEY"
    assert result["summary"]["ok"] is False


def test_audit_flags_non_canonical(store, tmp_path):
    (tmp_path / ".env.weirdprofile").write_text("A=1\n", encoding="utf-8")
    result = audit_env_files(store, directory=str(tmp_path), check_registry_urls=False)
    assert ".env.weirdprofile" in result["non_canonical_files"]


def test_audit_url_mismatch_against_registry(store, tmp_path):
    make_service(store, name="platform-admin", port=9000)
    (tmp_path / ".env.local-dev").write_text("URL_ADMIN=http://wronghost:1\n", encoding="utf-8")
    result = audit_env_files(store, directory=str(tmp_path), check_registry_urls=True)
    assert result["url_issues_count"] == 1
    assert result["url_issues"][0]["expected"] == "http://localhost:9000"


# ── redact_env_secrets ────────────────────────────────────────────────────── #


def test_redact_auto_detect(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "JWT_SECRET_KEY=realsecret123\nDB_PASSWORD=toor\nPLAIN=value\n", encoding="utf-8"
    )
    result = redact_env_secrets(store, paths=[str(env)])
    assert result["total_changes"] == 2
    content = env.read_text(encoding="utf-8")
    assert "JWT_SECRET_KEY=${JWT_SECRET_KEY}" in content
    assert "DB_PASSWORD=${DB_PASSWORD}" in content
    assert "PLAIN=value" in content


def test_redact_explicit_keys(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("PLAIN=value\nANOTHER=x\n", encoding="utf-8")
    result = redact_env_secrets(store, paths=[str(env)], keys=["PLAIN"], auto_detect=False)
    assert result["total_changes"] == 1
    assert "PLAIN=${PLAIN}" in env.read_text(encoding="utf-8")


def test_redact_dry_run(store, tmp_path):
    env = tmp_path / ".env"
    original = "JWT_SECRET_KEY=realsecret123\n"
    env.write_text(original, encoding="utf-8")
    result = redact_env_secrets(store, paths=[str(env)], dry_run=True)
    assert result["dry_run"] is True
    assert result["total_changes"] == 1
    assert env.read_text(encoding="utf-8") == original


def test_redact_file_not_found(store):
    result = redact_env_secrets(store, paths=["/no/such/file.env"])
    assert result["errors"][0]["error"] == "FileNotFound"


def test_redact_skips_already_ref(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("JWT_SECRET_KEY=${JWT_SECRET_KEY}\n", encoding="utf-8")
    result = redact_env_secrets(store, paths=[str(env)])
    assert result["total_changes"] == 0
