"""Testes das ferramentas de workspace."""

from __future__ import annotations

from src.tools.workspace_tool import (
    WORKSPACE_NS,
    get_workspace_config,
    list_workspace_config,
    set_workspace_config,
)


class TestSetWorkspaceConfig:
    def test_set_simple_key(self, store):
        result = set_workspace_config(store, key="editor", value="code")
        assert result["key"] == "EDITOR"
        assert result["action"] == "set"
        assert store.get(WORKSPACE_NS, "EDITOR") == "code"

    def test_set_repos_root_existing_dir(self, store, tmp_path):
        result = set_workspace_config(store, key="REPOS_ROOT", value=str(tmp_path))
        assert result["key"] == "REPOS_ROOT"
        assert result["resolved"] == str(tmp_path.resolve())

    def test_set_repos_root_missing_dir_errors(self, store, tmp_path):
        missing = tmp_path / "does_not_exist"
        result = set_workspace_config(store, key="REPOS_ROOT", value=str(missing))
        assert "error" in result
        assert "tip" in result
        assert store.get(WORKSPACE_NS, "REPOS_ROOT") is None

    def test_set_repos_root_create_dir(self, store, tmp_path):
        target = tmp_path / "new_repos"
        result = set_workspace_config(store, key="REPOS_ROOT", value=str(target), create_dir=True)
        assert target.exists()
        assert result["key"] == "REPOS_ROOT"

    def test_set_repos_root_existing_path_skips_dir_check(self, store, tmp_path):
        # set_workspace_config only runs path validation when the path does NOT
        # exist; an existing path (even a file) is accepted and stored as-is.
        f = tmp_path / "afile.txt"
        f.write_text("x", encoding="utf-8")
        result = set_workspace_config(store, key="REPOS_ROOT", value=str(f))
        assert result["action"] == "set"
        assert store.get("workspace", "REPOS_ROOT") == str(f)


class TestGetWorkspaceConfig:
    def test_get_specific_key_from_store(self, store):
        set_workspace_config(store, key="PYTHON_BIN", value="python3.12")
        result = get_workspace_config(store, key="python_bin")
        assert result["found"] is True
        assert result["value"] == "python3.12"
        assert result["source"] == "store"

    def test_get_specific_key_env_fallback(self, store, monkeypatch):
        monkeypatch.setenv("WORKSPACE_EDITOR", "vim")
        result = get_workspace_config(store, key="EDITOR")
        assert result["found"] is True
        assert result["value"] == "vim"
        assert result["source"] == "env_fallback"

    def test_get_repos_root_deploy_env_fallback(self, store, monkeypatch):
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.setenv("DEPLOY_REPOS_ROOT", "/deploy/repos")
        result = get_workspace_config(store, key="REPOS_ROOT")
        assert result["value"] == "/deploy/repos"

    def test_get_missing_key(self, store, monkeypatch):
        monkeypatch.delenv("WORKSPACE_NOPE", raising=False)
        result = get_workspace_config(store, key="NOPE")
        assert result["found"] is False
        assert result["value"] is None

    def test_get_all_from_store(self, store, monkeypatch):
        monkeypatch.delenv("DEPLOY_REPOS_ROOT", raising=False)
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
        set_workspace_config(store, key="EDITOR", value="nano")
        result = get_workspace_config(store)
        assert result["namespace"] == WORKSPACE_NS
        assert result["config"]["EDITOR"] == {"value": "nano", "source": "store"}
        assert "REPOS_ROOT" in result["canonical_keys"]

    def test_get_all_repos_root_from_env(self, store, monkeypatch):
        monkeypatch.delenv("DEPLOY_REPOS_ROOT", raising=False)
        monkeypatch.setenv("REPOS_ROOT", "/env/repos")
        result = get_workspace_config(store)
        assert result["config"]["REPOS_ROOT"] == {"value": "/env/repos", "source": "env"}


class TestListWorkspaceConfig:
    def test_lists_canonical_and_missing(self, store, monkeypatch):
        monkeypatch.delenv("DEPLOY_REPOS_ROOT", raising=False)
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
        result = list_workspace_config(store)
        keys = {r["key"] for r in result["config"]}
        assert {"REPOS_ROOT", "PYTHON_BIN", "EDITOR", "DEFAULT_ENV"} <= keys
        assert "REPOS_ROOT" in result["missing_canonical"]
        assert result["setup_tip"] is not None

    def test_lists_extra_non_canonical_key(self, store, monkeypatch):
        monkeypatch.delenv("DEPLOY_REPOS_ROOT", raising=False)
        monkeypatch.delenv("REPOS_ROOT", raising=False)
        monkeypatch.delenv("WORKSPACE_REPOS_ROOT", raising=False)
        set_workspace_config(store, key="CUSTOM_THING", value="42")
        result = list_workspace_config(store)
        extra = [r for r in result["config"] if r["key"] == "CUSTOM_THING"]
        assert extra and extra[0]["canonical"] is False

    def test_env_fallback_marks_set(self, store, monkeypatch):
        monkeypatch.setenv("REPOS_ROOT", "/env/repos")
        result = list_workspace_config(store)
        repos = [r for r in result["config"] if r["key"] == "REPOS_ROOT"][0]
        assert repos["set"] is True
        assert repos["source"] == "env"
        assert "REPOS_ROOT" not in result["missing_canonical"]
