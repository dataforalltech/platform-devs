from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tools.test_tool import run_e2e_tests, run_unit_tests


def _make_proc(stdout: str = "", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


# ---------- run_unit_tests ----------


def test_run_unit_tests_pytest_success(store, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
    with patch("subprocess.run", return_value=_make_proc("3 passed in 1.5s")):
        result = run_unit_tests(store, settings, repo_path=str(tmp_path))
    assert result["framework"] == "pytest"
    assert result["passed"] == 3
    assert result["failed"] == 0
    assert result["status"] == "passed"
    assert "run_id" in result


def test_run_unit_tests_with_coverage(store, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
    output = "5 passed in 2s\nTOTAL   100   15   85%"
    with patch("subprocess.run", return_value=_make_proc(output)):
        result = run_unit_tests(
            store, settings, repo_path=str(tmp_path), coverage=True
        )
    assert result["coverage_pct"] == 85.0
    assert result["passed"] == 5


def test_run_unit_tests_framework_detection_python(store, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
    with patch("subprocess.run", return_value=_make_proc("1 passed in 0.5s")):
        result = run_unit_tests(store, settings, repo_path=str(tmp_path))
    assert result["framework"] == "pytest"


def test_run_unit_tests_framework_detection_jest(store, settings, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}, "devDependencies": {"jest": "^29"}}')
    with patch("subprocess.run", return_value=_make_proc("1 passed", returncode=0)):
        result = run_unit_tests(
            store, settings, repo_path=str(tmp_path), framework="auto"
        )
    assert result["framework"] == "jest"


def test_run_unit_tests_missing_repo_validation(store, settings):
    result = run_unit_tests(store, settings, repo_path="")
    assert result["error"] == "ValidationError"
    assert "repo_path" in result["details"]


def test_run_e2e_tests_playwright_python(store, settings, tmp_path):
    (tmp_path / "test_login.py").write_text("def test_login(): pass")
    with patch("subprocess.run", return_value=_make_proc("2 passed in 5s")):
        result = run_e2e_tests(
            store, settings, test_path=str(tmp_path), base_url="http://localhost:8000"
        )
    assert result["browser"] == "chromium"
    assert result["passed"] == 2
    assert result["status"] == "passed"


def test_run_e2e_tests_spec_ts(store, settings, tmp_path):
    (tmp_path / "login.spec.ts").write_text("test('login', () => {})")
    with patch("subprocess.run", return_value=_make_proc("3 passed", returncode=0)):
        result = run_e2e_tests(
            store, settings, test_path=str(tmp_path), base_url="http://localhost:3000"
        )
    assert result["base_url"] == "http://localhost:3000"
    assert "run_id" in result


def test_run_e2e_tests_missing_base_url(store, settings, tmp_path):
    result = run_e2e_tests(store, settings, test_path=str(tmp_path), base_url="")
    assert result["error"] == "ValidationError"
    assert "base_url" in result["details"]
