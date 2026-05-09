"""Testes do scripts/precommit_validate.py.

Hook tem 2 superfícies testáveis sem rodar git/MCP de verdade:
1. Funções puras de detecção (_detect_flags, _detect_layers, _is_special_commit).
2. Lógica de exit code (_print_result com diferentes risk levels).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import precommit_validate as hook  # noqa: E402  (import after sys.path manip)


# --------------------------- _detect_flags --------------------------- #
def test_flags_empty_when_no_files():
    flags = hook._detect_flags(diff="", files=[])
    assert flags == {
        "changes_contracts": False,
        "adds_fallback": False,
        "adds_dependency": False,
        "modifies_security": False,
    }


def test_adds_dependency_true_for_pyproject():
    flags = hook._detect_flags(diff="", files=["a/b/pyproject.toml"])
    assert flags["adds_dependency"] is True


def test_adds_dependency_true_for_requirements_txt():
    flags = hook._detect_flags(diff="", files=["requirements.txt"])
    assert flags["adds_dependency"] is True


def test_adds_dependency_true_for_package_json():
    flags = hook._detect_flags(diff="", files=["frontend/package.json"])
    assert flags["adds_dependency"] is True


def test_adds_dependency_false_for_random_file():
    flags = hook._detect_flags(diff="", files=["src/foo.py", "tests/test_foo.py"])
    assert flags["adds_dependency"] is False


def test_other_flags_always_false():
    """Por design, outros flags ficam False — server detecta via regex."""
    flags = hook._detect_flags(
        diff="+ try:\n+     except Exception: pass",
        files=["src/foo.py"],
    )
    assert flags["adds_fallback"] is False
    assert flags["changes_contracts"] is False
    assert flags["modifies_security"] is False


# --------------------------- _detect_layers --------------------------- #
def test_layers_backend_for_app_path():
    layers = hook._detect_layers(["app/services/order.py"])
    assert "backend" in layers


def test_layers_database_for_alembic():
    layers = hook._detect_layers(["alembic/versions/001_init.py"])
    assert "database" in layers


def test_layers_testing_for_tests_path():
    layers = hook._detect_layers(["tests/test_foo.py"])
    assert "testing" in layers


def test_layers_frontend_for_tsx():
    layers = hook._detect_layers(["frontend/src/App.tsx"])
    assert "frontend" in layers


def test_layers_security_for_auth_path():
    layers = hook._detect_layers(["app/auth/jwt_manager.py"])
    assert "security" in layers


def test_layers_infrastructure_for_dockerfile():
    layers = hook._detect_layers(["Dockerfile", "docker-compose.yml"])
    assert "infrastructure" in layers


def test_layers_multiple_for_mixed_change():
    layers = hook._detect_layers(
        [
            "app/services/payment.py",
            "tests/test_payment.py",
            "alembic/versions/002_payments.py",
        ]
    )
    assert {"backend", "testing", "database"} <= set(layers)


def test_layers_empty_for_random_file():
    layers = hook._detect_layers(["README.md", "LICENSE"])
    assert layers == []


# --------------------------- _print_result exit codes --------------------------- #
def test_print_result_blocks_on_critical(capsys):
    rc = hook._print_result(
        {"approved": False, "risk_level": "critical", "violations": ["x"], "required_actions": []},
        block_on_high=False,
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "BLOCK" in err
    assert "critical" in err


def test_print_result_blocks_on_unapproved_even_if_low(capsys):
    rc = hook._print_result(
        {"approved": False, "risk_level": "low", "violations": [], "required_actions": []},
        block_on_high=False,
    )
    assert rc == 1


def test_print_result_warns_on_high_by_default(capsys):
    rc = hook._print_result(
        {"approved": True, "risk_level": "high", "violations": [], "required_actions": []},
        block_on_high=False,
    )
    assert rc == 0
    assert "WARN" in capsys.readouterr().err


def test_print_result_blocks_on_high_when_requested(capsys):
    rc = hook._print_result(
        {"approved": True, "risk_level": "high", "violations": [], "required_actions": []},
        block_on_high=True,
    )
    assert rc == 1


def test_print_result_warns_on_medium(capsys):
    rc = hook._print_result(
        {"approved": True, "risk_level": "medium", "violations": [], "required_actions": []},
        block_on_high=False,
    )
    assert rc == 0
    assert "WARN" in capsys.readouterr().err


def test_print_result_ok_on_low(capsys):
    rc = hook._print_result(
        {"approved": True, "risk_level": "low", "violations": [], "required_actions": []},
        block_on_high=False,
    )
    assert rc == 0
    assert "OK" in capsys.readouterr().err


# --------------------------- _is_special_commit --------------------------- #
def test_is_special_commit_with_merge_head(tmp_path, monkeypatch):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "MERGE_HEAD").write_text("deadbeef")

    # Forçar _git("rev-parse --git-dir") a retornar nosso tmp_path/.git
    def fake_git(args):
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir) + "\n"
        return ""

    monkeypatch.setattr(hook, "_git", fake_git)
    assert hook._is_special_commit() is True


def test_is_special_commit_normal_state(tmp_path, monkeypatch):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_git(args):
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir) + "\n"
        return ""

    monkeypatch.setattr(hook, "_git", fake_git)
    assert hook._is_special_commit() is False


def test_is_special_commit_during_rebase(tmp_path, monkeypatch):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "rebase-merge").mkdir()

    def fake_git(args):
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir) + "\n"
        return ""

    monkeypatch.setattr(hook, "_git", fake_git)
    assert hook._is_special_commit() is True


# --------------------------- env var overrides --------------------------- #
def test_repo_name_uses_env_var_when_set(monkeypatch):
    monkeypatch.setenv("PRECOMMIT_REPO_NAME", "my-explicit-repo")
    assert hook._repo_name() == "my-explicit-repo"


def test_task_description_uses_env_var_when_set(monkeypatch):
    monkeypatch.setenv("PRECOMMIT_TASK_DESCRIPTION", "Custom task")
    assert hook._task_description(["a.py"]) == "Custom task"


# --------------------------- diff truncation --------------------------- #
def test_staged_diff_truncates_large_diffs(monkeypatch):
    big = "x" * (hook._MAX_DIFF_CHARS + 5000)
    monkeypatch.setattr(hook, "_git", lambda args: big)
    out = hook._staged_diff()
    assert len(out) <= hook._MAX_DIFF_CHARS + 50  # extra para "(truncated)"
    assert "truncated" in out
