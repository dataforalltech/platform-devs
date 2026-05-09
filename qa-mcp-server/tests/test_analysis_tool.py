from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.tools.analysis_tool import (
    analyze_complexity,
    check_dependencies,
    run_linter,
    run_security_scan,
    run_type_check,
)

_RUFF_JSON = json.dumps(
    [
        {
            "filename": "src/main.py",
            "code": "F401",
            "message": "unused import os",
            "location": {"row": 1, "column": 1},
        },
        {
            "filename": "src/utils.py",
            "code": "E711",
            "message": "comparison to None",
            "location": {"row": 10, "column": 5},
        },
    ]
)

_BANDIT_JSON = json.dumps(
    {
        "results": [
            {
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "filename": "src/utils.py",
                "line_number": 42,
                "test_id": "B105",
                "issue_text": "Possible hardcoded password",
            },
            {
                "issue_severity": "MEDIUM",
                "issue_confidence": "MEDIUM",
                "filename": "src/utils.py",
                "line_number": 10,
                "test_id": "B310",
                "issue_text": "Use of urllib",
            },
        ]
    }
)

_PIP_AUDIT_JSON = json.dumps(
    {
        "dependencies": [
            {
                "name": "requests",
                "version": "2.25.0",
                "vulns": [
                    {
                        "id": "CVE-2023-1234",
                        "description": "SSRF vulnerability",
                        "fix_versions": ["2.31.0"],
                    }
                ],
            },
            {"name": "flask", "version": "2.0.0", "vulns": []},
        ]
    }
)

_RADON_JSON = json.dumps(
    {
        "src/processor.py": [
            {"name": "process_data", "complexity": 18, "rank": "C"},
            {"name": "helper", "complexity": 3, "rank": "A"},
        ]
    }
)

_MYPY_OUTPUT = (
    "src/main.py:10: error: Argument 1 to \"foo\" has incompatible type\n"
    "src/utils.py:5: warning: Unused variable x\n"
    "Found 1 error in 1 file (checked 20 source files)\n"
)


def _make_proc(stdout="", stderr="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


# ---------- run_linter ----------


def test_run_linter_python_ruff(store, settings, tmp_path):
    (tmp_path / "main.py").write_text("import os\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _RUFF_JSON, ""),
    ):
        result = run_linter(store, settings, repo_path=str(tmp_path))
    assert result["tool"] == "ruff"
    assert result["errors"] == 2  # F401 + E711 are errors (not W codes)
    assert len(result["issues"]) == 2
    assert result["issues"][0]["code"] == "F401"


def test_run_linter_auto_detects_python(store, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, "[]", ""),
    ):
        result = run_linter(store, settings, repo_path=str(tmp_path))
    assert result["framework"] == "python"
    assert result["tool"] == "ruff"


def test_run_linter_tool_not_found(store, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=FileNotFoundError("ruff not found"),
    ):
        result = run_linter(store, settings, repo_path=str(tmp_path))
    assert result["error"] == "tool_not_found"
    assert result["tool"] == "ruff"


# ---------- run_security_scan ----------


def test_run_security_scan_bandit(store, settings, tmp_path):
    (tmp_path / "app.py").write_text("password = 'secret'\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _BANDIT_JSON, ""),
    ):
        result = run_security_scan(store, settings, repo_path=str(tmp_path))
    assert result["tool"] == "bandit"
    assert result["high"] == 1
    assert result["medium"] == 1
    assert result["total_issues"] == 2


def test_run_security_scan_high_issue(store, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    high_only = json.dumps(
        {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "filename": "src/app.py",
                    "line_number": 1,
                    "test_id": "B602",
                    "issue_text": "subprocess call with shell=True",
                }
            ]
        }
    )
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, high_only, ""),
    ):
        result = run_security_scan(store, settings, repo_path=str(tmp_path))
    assert result["high"] == 1
    assert result["findings"][0]["severity"] == "HIGH"


# ---------- check_dependencies ----------


def test_check_dependencies_python_pip_audit(store, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _PIP_AUDIT_JSON, ""),
    ):
        result = check_dependencies(store, settings, repo_path=str(tmp_path))
    assert result["tool"] == "pip-audit"
    assert result["vulnerabilities"] == 1
    assert result["findings"][0]["package"] == "requests"
    assert result["findings"][0]["fix_version"] == "2.31.0"


def test_check_dependencies_no_vulnerabilities(store, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
    clean_json = json.dumps(
        {"dependencies": [{"name": "flask", "version": "3.0.0", "vulns": []}]}
    )
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, clean_json, ""),
    ):
        result = check_dependencies(store, settings, repo_path=str(tmp_path))
    assert result["vulnerabilities"] == 0
    assert result["findings"] == []


# ---------- run_type_check ----------


def test_run_type_check_mypy_no_errors(store, settings, tmp_path):
    (tmp_path / "app.py").write_text("x: int = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, "Success: no issues found in 5 source files", ""),
    ):
        result = run_type_check(store, settings, repo_path=str(tmp_path))
    assert result["tool"] == "mypy"
    assert result["errors"] == 0


def test_run_type_check_mypy_with_errors(store, settings, tmp_path):
    (tmp_path / "app.py").write_text("x: str = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, _MYPY_OUTPUT, ""),
    ):
        result = run_type_check(store, settings, repo_path=str(tmp_path))
    assert result["errors"] == 1
    assert result["warnings"] == 1
    assert result["issues"][0]["file"] == "src/main.py"
    assert result["issues"][0]["severity"] == "error"


# ---------- analyze_complexity ----------


def test_analyze_complexity_radon(store, settings, tmp_path):
    (tmp_path / "processor.py").write_text("def process_data(): pass\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _RADON_JSON, ""),
    ):
        result = analyze_complexity(store, settings, repo_path=str(tmp_path), threshold=10)
    assert result["tool"] == "radon"
    assert result["total_functions"] == 2
    assert result["above_threshold"] == 1
    assert result["hotspots"][0]["function"] == "process_data"
    assert result["hotspots"][0]["complexity"] == 18


def test_analyze_complexity_above_threshold(store, settings, tmp_path):
    (tmp_path / "complex.py").write_text("def f(): pass\n")
    radon_data = json.dumps(
        {
            "src/complex.py": [
                {"name": "f", "complexity": 25, "rank": "D"},
                {"name": "g", "complexity": 5, "rank": "A"},
            ]
        }
    )
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, radon_data, ""),
    ):
        result = analyze_complexity(store, settings, repo_path=str(tmp_path), threshold=10)
    assert result["above_threshold"] == 1
    assert result["hotspots"][0]["complexity"] == 25
