"""Testes das ferramentas de ambiente (env_tool) — store e disco."""

from __future__ import annotations

from src.tools.env_tool import (
    _is_hardcoded_secret,
    _is_secret_key,
    _parse_env_lines,
    audit_env_files,
    get_env_config,
    push_env_to_store,
    read_env_file,
    redact_env_secrets,
    set_env_var,
    sync_env_file,
)


class TestSecretDetection:
    def test_is_secret_key_by_suffix(self):
        assert _is_secret_key("DB_PASSWORD")
        assert _is_secret_key("GITHUB_TOKEN")
        assert _is_secret_key("SIGNING_KEY")
        assert _is_secret_key("MY_SECRET")

    def test_is_secret_key_by_infix(self):
        assert _is_secret_key("PRIVATE_THING")
        assert _is_secret_key("SOME_API_KEY")

    def test_is_not_secret_key(self):
        assert not _is_secret_key("DATABASE_URL")
        assert not _is_secret_key("PORT")

    def test_hardcoded_secret_true_for_real_value(self):
        assert _is_hardcoded_secret("JWT_SECRET_KEY", "XrDsCabc123")

    def test_hardcoded_secret_false_for_non_secret_key(self):
        assert not _is_hardcoded_secret("DATABASE_URL", "postgres://x")

    def test_hardcoded_secret_false_for_empty(self):
        assert not _is_hardcoded_secret("DB_PASSWORD", "")

    def test_hardcoded_secret_false_for_reference(self):
        assert not _is_hardcoded_secret("DB_PASSWORD", "${DB_PASSWORD}")
        assert not _is_hardcoded_secret("DB_PASSWORD", "/run/secrets/db")
        assert not _is_hardcoded_secret("DB_PASSWORD", "dev-local")
        assert not _is_hardcoded_secret("DB_PASSWORD", "changeme")
        assert not _is_hardcoded_secret("DB_PASSWORD", "<placeholder>")
        assert not _is_hardcoded_secret("DB_PASSWORD", "xxxx")


class TestParseEnvLines:
    def test_parses_kv_blank_and_comment(self):
        text = "# comment\n\nKEY=value\nBAD LINE\n"
        parsed = _parse_env_lines(text)
        # comment
        assert parsed[0] == ("", None, "# comment")
        # blank
        assert parsed[1] == ("", None, "")
        # kv
        assert parsed[2] == ("KEY", "value", "KEY=value")
        # not a kv → preserved
        assert parsed[3] == ("", None, "BAD LINE")


class TestGetEnvConfig:
    def test_returns_all(self, store):
        set_env_var(store, "dev", "DATABASE_URL", "postgres://x")
        set_env_var(store, "dev", "REDIS_URL", "redis://x")
        result = get_env_config(store, "dev")
        assert result["count"] == 2

    def test_key_pattern_filter(self, store):
        set_env_var(store, "dev", "DATABASE_URL", "postgres://x")
        set_env_var(store, "dev", "REDIS_URL", "redis://x")
        result = get_env_config(store, "dev", key_pattern="database")
        assert result["config"] == {"DATABASE_URL": "postgres://x"}

    def test_limit_truncates(self, store):
        for i in range(5):
            set_env_var(store, "dev", f"K{i}", str(i))
        result = get_env_config(store, "dev", limit=2)
        assert result["count"] == 2


class TestSyncEnvFile:
    def test_no_vars_returns_failure(self, store, tmp_path):
        result = sync_env_file(store, str(tmp_path / ".env"), "empty")
        assert result["success"] is False
        assert "error" in result

    def test_merge_keeps_local_vars(self, store, tmp_path):
        path = tmp_path / ".env.dev"
        path.write_text("LOCAL_ONLY=keepme\nDATABASE_URL=old\n", encoding="utf-8")
        set_env_var(store, "dev", "DATABASE_URL", "postgres://new")
        result = sync_env_file(store, str(path), "dev", merge=True)
        assert result["success"] is True
        content = path.read_text(encoding="utf-8")
        assert "LOCAL_ONLY=keepme" in content
        # store value wins over the local one
        assert "DATABASE_URL=postgres://new" in content

    def test_no_merge_overwrites(self, store, tmp_path):
        path = tmp_path / ".env.dev"
        path.write_text("LOCAL_ONLY=dropme\n", encoding="utf-8")
        set_env_var(store, "dev", "DATABASE_URL", "postgres://x")
        result = sync_env_file(store, str(path), "dev", merge=False)
        assert result["success"] is True
        content = path.read_text(encoding="utf-8")
        assert "LOCAL_ONLY" not in content
        assert "DATABASE_URL=postgres://x" in content


class TestReadEnvFile:
    def test_file_not_found(self, store, tmp_path):
        result = read_env_file(store, path=str(tmp_path / "nope.env"))
        assert result["error"] == "FileNotFound"

    def test_reads_variables_ignoring_comments(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("# header\nA=1\n\nB=2\nnokv\n", encoding="utf-8")
        result = read_env_file(store, path=str(path))
        assert result["variables"] == {"A": "1", "B": "2"}
        assert result["count"] == 2

    def test_key_filter(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("DATABASE_URL=x\nPORT=8000\n", encoding="utf-8")
        result = read_env_file(store, path=str(path), key_filter="url")
        assert result["variables"] == {"DATABASE_URL": "x"}


class TestAuditEnvFiles:
    def test_detects_hardcoded_secret_and_noncanonical(self, store, tmp_path):
        (tmp_path / ".env.weird").write_text(
            "JWT_SECRET_KEY=realsecretvalue\nPORT=8000\n", encoding="utf-8"
        )
        result = audit_env_files(store, directory=str(tmp_path))
        assert result["hardcoded_secrets_count"] == 1
        secret = result["hardcoded_secrets"][0]
        assert secret["key"] == "JWT_SECRET_KEY"
        assert "***" in secret["value_preview"]
        assert secret["in_store"] is False
        assert ".env.weird" in result["non_canonical_files"]
        assert result["summary"]["ok"] is False

    def test_canonical_file_no_secrets_is_ok(self, store, tmp_path):
        (tmp_path / ".env.local-dev").write_text("PORT=8000\nDEBUG=true\n", encoding="utf-8")
        result = audit_env_files(store, directory=str(tmp_path))
        assert result["hardcoded_secrets_count"] == 0
        assert result["non_canonical_files"] == []
        assert result["summary"]["ok"] is True

    def test_in_store_true_when_covered(self, store, tmp_path):
        (tmp_path / ".env.local-dev").write_text("DB_PASSWORD=hardcoded123\n", encoding="utf-8")
        store.set("env.local-dev", "DB_PASSWORD", "hardcoded123")
        result = audit_env_files(store, directory=str(tmp_path), check_store=True)
        assert result["hardcoded_secrets"][0]["in_store"] is True

    def test_short_value_preview(self, store, tmp_path):
        (tmp_path / ".env.local-dev").write_text("API_KEY=ab\n", encoding="utf-8")
        result = audit_env_files(store, directory=str(tmp_path))
        assert result["hardcoded_secrets"][0]["value_preview"] == "***"


class TestRedactEnvSecrets:
    def test_dry_run_does_not_write(self, store, tmp_path):
        path = tmp_path / ".env"
        original = "JWT_SECRET_KEY=supersecret\nPORT=8000\n"
        path.write_text(original, encoding="utf-8")
        result = redact_env_secrets(store, paths=[str(path)], dry_run=True)
        assert result["dry_run"] is True
        assert result["total_changes"] == 1
        assert path.read_text(encoding="utf-8") == original

    def test_writes_reference(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("JWT_SECRET_KEY=supersecret\nPORT=8000\n", encoding="utf-8")
        result = redact_env_secrets(store, paths=[str(path)], dry_run=False)
        assert result["files_modified"] == [str(path.resolve())]
        content = path.read_text(encoding="utf-8")
        assert "JWT_SECRET_KEY=${JWT_SECRET_KEY}" in content
        assert "PORT=8000" in content

    def test_explicit_keys(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("PLAIN_VAR=redactme\n", encoding="utf-8")
        result = redact_env_secrets(store, paths=[str(path)], keys=["PLAIN_VAR"], auto_detect=False)
        assert result["total_changes"] == 1
        assert "PLAIN_VAR=${PLAIN_VAR}" in path.read_text(encoding="utf-8")

    def test_file_not_found_reports_error(self, store, tmp_path):
        result = redact_env_secrets(store, paths=[str(tmp_path / "nope.env")])
        assert any("FileNotFound" in e for e in result["errors"])
        assert result["files_processed"] == 0

    def test_no_changes_when_nothing_matches(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("PORT=8000\n", encoding="utf-8")
        result = redact_env_secrets(store, paths=[str(path)])
        assert result["total_changes"] == 0
        assert result["files_modified"] == []


class TestPushEnvToStore:
    def test_file_not_found(self, store, tmp_path):
        result = push_env_to_store(store, path=str(tmp_path / "nope.env"), environment="dev")
        assert result["error"] == "FileNotFound"

    def test_pushes_vars(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("# c\nDATABASE_URL=x\nAPI_KEY=secret\n", encoding="utf-8")
        result = push_env_to_store(store, path=str(path), environment="dev")
        assert result["pushed"] == 2
        assert store.get("env.dev", "DATABASE_URL") == "x"

    def test_skips_existing_without_overwrite(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("DATABASE_URL=new\n", encoding="utf-8")
        store.set("env.dev", "DATABASE_URL", "old")
        result = push_env_to_store(store, path=str(path), environment="dev", overwrite=False)
        assert result["skipped"] == 1
        assert result["pushed"] == 0
        assert store.get("env.dev", "DATABASE_URL") == "old"

    def test_overwrite_true_replaces(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("DATABASE_URL=new\n", encoding="utf-8")
        store.set("env.dev", "DATABASE_URL", "old")
        result = push_env_to_store(store, path=str(path), environment="dev", overwrite=True)
        assert result["pushed"] == 1
        assert store.get("env.dev", "DATABASE_URL") == "new"

    def test_secrets_only_skips_non_secrets(self, store, tmp_path):
        path = tmp_path / ".env"
        path.write_text("DATABASE_URL=x\nAPI_KEY=secret\n", encoding="utf-8")
        result = push_env_to_store(store, path=str(path), environment="dev", secrets_only=True)
        assert result["pushed"] == 1
        assert store.get("env.dev", "API_KEY") == "secret"
        assert store.get("env.dev", "DATABASE_URL") is None
