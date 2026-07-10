"""Testes para a skill de healthcheck: ensure_all_repos_healthy e helpers.

time.sleep é patchado para no-op (testes rápidos); toda I/O via client/settings é mockada.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.tools import healthcheck_tool
from src.tools.healthcheck_tool import (
    _acr_status,
    _ci_status,
    _wait_for_ci,
    ensure_all_repos_healthy,
)


@pytest.fixture
def acr_settings():
    from src.config.settings import DeploySettings

    return DeploySettings(
        github_token="t",
        github_org="test-org",
        acr_username="u",
        acr_password="p",
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Neutraliza time.sleep em todos os testes deste módulo."""
    monkeypatch.setattr(healthcheck_tool.time, "sleep", lambda *_a, **_k: None)


# ─────────────────────────────────────────────────────────────────────────── #
# _ci_status                                                                    #
# ─────────────────────────────────────────────────────────────────────────── #
class TestCiStatus:
    def test_success(self):
        client = MagicMock()
        client.list_workflow_runs.return_value = [
            {"status": "completed", "conclusion": "success", "id": 1, "html_url": "u"}
        ]
        result = _ci_status(client, "repo", "ci.yml", "develop")
        assert result["status"] == "success"

    def test_failing(self):
        client = MagicMock()
        client.list_workflow_runs.return_value = [
            {"status": "completed", "conclusion": "failure", "id": 2, "html_url": "u"}
        ]
        result = _ci_status(client, "repo", "ci.yml", "develop")
        assert result["status"] == "failing"

    def test_in_progress(self):
        client = MagicMock()
        client.list_workflow_runs.return_value = [
            {"status": "in_progress", "conclusion": None, "id": 3, "html_url": "u"}
        ]
        result = _ci_status(client, "repo", "ci.yml", "develop")
        assert result["status"] == "in_progress"

    def test_no_workflow_when_client_raises(self):
        from src.knowledge.github_client import GitHubClientError

        client = MagicMock()
        client.list_workflow_runs.side_effect = GitHubClientError("no wf")
        result = _ci_status(client, "repo", "ci.yml", "develop")
        assert result["status"] == "no_workflow"

    def test_no_runs_when_never_ran(self):
        client = MagicMock()
        # primeira chamada (com branch) vazia, segunda (sem branch) também vazia
        client.list_workflow_runs.side_effect = [[], []]
        result = _ci_status(client, "repo", "ci.yml", "develop")
        assert result["status"] == "no_runs"

    def test_falls_back_to_any_branch_run(self):
        client = MagicMock()
        client.list_workflow_runs.side_effect = [
            [],  # nada na branch
            [{"status": "completed", "conclusion": "success", "id": 5, "html_url": "u"}],
        ]
        result = _ci_status(client, "repo", "ci.yml", "develop")
        assert result["status"] == "success"


# ─────────────────────────────────────────────────────────────────────────── #
# _acr_status                                                                   #
# ─────────────────────────────────────────────────────────────────────────── #
class TestAcrStatus:
    def test_present(self, acr_settings, monkeypatch):
        monkeypatch.setattr(
            healthcheck_tool,
            "list_acr_images",
            lambda *a, **k: {"tags": [{"name": "v1"}]},
        )
        result = _acr_status(MagicMock(), acr_settings, "repo")
        assert result["status"] == "present"
        assert result["latest_tag"] == "v1"

    def test_missing(self, acr_settings, monkeypatch):
        monkeypatch.setattr(healthcheck_tool, "list_acr_images", lambda *a, **k: {"tags": []})
        result = _acr_status(MagicMock(), acr_settings, "repo")
        assert result["status"] == "missing"

    def test_error(self, acr_settings, monkeypatch):
        monkeypatch.setattr(
            healthcheck_tool,
            "list_acr_images",
            lambda *a, **k: {"error": "ConfigError", "details": "no creds"},
        )
        result = _acr_status(MagicMock(), acr_settings, "repo")
        assert result["status"] == "error"


# ─────────────────────────────────────────────────────────────────────────── #
# _wait_for_ci                                                                  #
# ─────────────────────────────────────────────────────────────────────────── #
class TestWaitForCi:
    def test_returns_success(self, monkeypatch):
        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "success"})
        assert _wait_for_ci(MagicMock(), "repo", "ci.yml", "develop", wait_seconds=60) == "success"

    def test_returns_failing(self, monkeypatch):
        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "failing"})
        assert _wait_for_ci(MagicMock(), "repo", "ci.yml", "develop", wait_seconds=60) == "failing"

    def test_timeout(self, monkeypatch):
        # ci sempre in_progress + relógio que estoura o deadline imediatamente
        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "in_progress"})
        times = iter([0, 0, 1000, 2000, 3000])
        monkeypatch.setattr(healthcheck_tool.time, "time", lambda: next(times))
        result = _wait_for_ci(MagicMock(), "repo", "ci.yml", "develop", wait_seconds=10, poll_interval=1)
        assert result == "timeout"


# ─────────────────────────────────────────────────────────────────────────── #
# ensure_all_repos_healthy                                                      #
# ─────────────────────────────────────────────────────────────────────────── #
class TestEnsureAllReposHealthy:
    def test_dry_run_reports_without_remediation(self, acr_settings, monkeypatch):
        client = MagicMock()
        client.list_repos.return_value = [{"name": "healthy-repo"}, {"name": "sick-repo"}]

        def fake_ci(_client, name, *_a, **_k):
            return {"status": "success"} if name == "healthy-repo" else {"status": "failing"}

        def fake_acr(_client, _settings, name):
            return {"status": "present"} if name == "healthy-repo" else {"status": "missing"}

        monkeypatch.setattr(healthcheck_tool, "_ci_status", fake_ci)
        monkeypatch.setattr(healthcheck_tool, "_acr_status", fake_acr)
        # Guardas: remediações NÃO devem ser chamadas em dry_run
        scaffold = MagicMock()
        trigger = MagicMock()
        setup = MagicMock()
        monkeypatch.setattr(healthcheck_tool, "scaffold_pipeline", scaffold)
        monkeypatch.setattr(healthcheck_tool, "trigger_workflow", trigger)
        monkeypatch.setattr(healthcheck_tool, "setup_repo", setup)

        result = ensure_all_repos_healthy(client, acr_settings, dry_run=True)

        assert result["dry_run"] is True
        assert result["summary"]["total"] == 2
        assert result["summary"]["healthy"] == 1
        sick = next(r for r in result["repos"] if r["name"] == "sick-repo")
        assert sick["health"] == "CI_FAILING_AND_ACR_MISSING"
        scaffold.assert_not_called()
        trigger.assert_not_called()
        setup.assert_not_called()

    def test_classifies_all_health_states(self, acr_settings, monkeypatch):
        client = MagicMock()
        client.list_repos.return_value = [
            {"name": "ok"},
            {"name": "ci-bad"},
            {"name": "acr-bad"},
            {"name": "both-bad"},
        ]
        ci_map = {
            "ok": "success",
            "ci-bad": "failing",
            "acr-bad": "success",
            "both-bad": "failing",
        }
        acr_map = {
            "ok": "present",
            "ci-bad": "present",
            "acr-bad": "missing",
            "both-bad": "missing",
        }
        monkeypatch.setattr(
            healthcheck_tool, "_ci_status", lambda _c, name, *a, **k: {"status": ci_map[name]}
        )
        monkeypatch.setattr(healthcheck_tool, "_acr_status", lambda _c, _s, name: {"status": acr_map[name]})

        result = ensure_all_repos_healthy(client, acr_settings, dry_run=True)
        health = {r["name"]: r["health"] for r in result["repos"]}
        assert health["ok"] == "HEALTHY"
        assert health["ci-bad"] == "CI_FAILING"
        assert health["acr-bad"] == "ACR_MISSING"
        assert health["both-bad"] == "CI_FAILING_AND_ACR_MISSING"

    def test_remediates_ci_failing_success(self, acr_settings, monkeypatch):
        client = MagicMock()
        client.list_repos.return_value = [{"name": "ci-bad"}]

        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "failing"})
        monkeypatch.setattr(healthcheck_tool, "_acr_status", lambda *a, **k: {"status": "present"})
        trigger = MagicMock(return_value={"dispatched": True})
        monkeypatch.setattr(healthcheck_tool, "trigger_workflow", trigger)
        monkeypatch.setattr(healthcheck_tool, "_wait_for_ci", lambda *a, **k: "success")

        result = ensure_all_repos_healthy(client, acr_settings, dry_run=False)

        trigger.assert_called_once()
        repo = result["repos"][0]
        assert repo["remediation"] == "ci_success"
        assert result["summary"]["healthy"] == 1

    def test_scaffolds_when_workflow_absent(self, acr_settings, monkeypatch):
        client = MagicMock()
        client.list_repos.return_value = [{"name": "new-repo"}]

        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "no_workflow"})
        monkeypatch.setattr(healthcheck_tool, "_acr_status", lambda *a, **k: {"status": "present"})
        scaffold = MagicMock(return_value={"committed": True})
        trigger = MagicMock(return_value={"dispatched": True})
        monkeypatch.setattr(healthcheck_tool, "scaffold_pipeline", scaffold)
        monkeypatch.setattr(healthcheck_tool, "trigger_workflow", trigger)
        monkeypatch.setattr(healthcheck_tool, "_wait_for_ci", lambda *a, **k: "success")

        ensure_all_repos_healthy(client, acr_settings, dry_run=False)

        scaffold.assert_called_once()
        assert scaffold.call_args.kwargs["templates"] == ["ci", "cd-dev"]

    def test_remediates_acr_missing(self, acr_settings, monkeypatch):
        client = MagicMock()
        client.list_repos.return_value = [{"name": "acr-bad"}]

        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "success"})
        monkeypatch.setattr(healthcheck_tool, "_acr_status", lambda *a, **k: {"status": "missing"})
        setup = MagicMock(return_value={"success": True})
        trigger = MagicMock(return_value={"dispatched": True})
        monkeypatch.setattr(healthcheck_tool, "setup_repo", setup)
        monkeypatch.setattr(healthcheck_tool, "trigger_workflow", trigger)

        result = ensure_all_repos_healthy(client, acr_settings, dry_run=False)

        setup.assert_called_once()
        trigger.assert_called_once()  # cd-dev dispatch
        assert result["repos"][0]["acr_status"] == "triggered"

    def test_ci_failure_blocks_acr_remediation(self, acr_settings, monkeypatch):
        client = MagicMock()
        client.list_repos.return_value = [{"name": "both-bad"}]

        monkeypatch.setattr(healthcheck_tool, "_ci_status", lambda *a, **k: {"status": "failing"})
        monkeypatch.setattr(healthcheck_tool, "_acr_status", lambda *a, **k: {"status": "missing"})
        setup = MagicMock(return_value={"success": True})
        trigger = MagicMock(return_value={"dispatched": True})
        monkeypatch.setattr(healthcheck_tool, "setup_repo", setup)
        monkeypatch.setattr(healthcheck_tool, "trigger_workflow", trigger)
        monkeypatch.setattr(healthcheck_tool, "_wait_for_ci", lambda *a, **k: "timeout")

        ensure_all_repos_healthy(client, acr_settings, dry_run=False)

        # CI ainda falhando (timeout) → não tenta setup_repo do ACR
        setup.assert_not_called()
