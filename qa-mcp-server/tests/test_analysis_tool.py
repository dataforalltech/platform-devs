"""Tools de análise (async) contra MySQL real (§16 / FID-02).

O banco (store) é REAL (tenant-scoped); as ferramentas externas (ruff/bandit/pip-audit/
mypy/tsc/radon via subprocess) seguem mockadas (FID-01 — duplo de serviço externo).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.tools.analysis_tool import (
    analyze_complexity,
    check_dependencies,
    run_linter,
    run_security_scan,
    run_type_check,
)

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]

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
    'src/main.py:10: error: Argument 1 to "foo" has incompatible type\n'
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


async def test_run_linter_python_ruff(store_a, settings, tmp_path):
    (tmp_path / "main.py").write_text("import os\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _RUFF_JSON, ""),
    ):
        result = await run_linter(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "ruff"
    assert result["errors"] == 2  # F401 + E711 are errors (not W codes)
    assert len(result["issues"]) == 2
    assert result["issues"][0]["code"] == "F401"
    assert "run_id" in result


async def test_run_linter_auto_detects_python(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, "[]", ""),
    ):
        result = await run_linter(store_a, settings, repo_path=str(tmp_path))
    assert result["framework"] == "python"
    assert result["tool"] == "ruff"


async def test_run_linter_tool_not_found(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=FileNotFoundError("ruff not found"),
    ):
        result = await run_linter(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "tool_not_found"
    assert result["tool"] == "ruff"


# ---------- run_security_scan ----------


async def test_run_security_scan_bandit(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("password = 'secret'\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _BANDIT_JSON, ""),
    ):
        result = await run_security_scan(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "bandit"
    assert result["high"] == 1
    assert result["medium"] == 1
    assert result["total_issues"] == 2


async def test_run_security_scan_high_issue(store_a, settings, tmp_path):
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
        result = await run_security_scan(store_a, settings, repo_path=str(tmp_path))
    assert result["high"] == 1
    assert result["findings"][0]["severity"] == "HIGH"


# ---------- check_dependencies ----------


async def test_check_dependencies_python_pip_audit(store_a, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _PIP_AUDIT_JSON, ""),
    ):
        result = await check_dependencies(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "pip-audit"
    assert result["vulnerabilities"] == 1
    assert result["findings"][0]["package"] == "requests"
    assert result["findings"][0]["fix_version"] == "2.31.0"


async def test_check_dependencies_no_vulnerabilities(store_a, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
    clean_json = json.dumps({"dependencies": [{"name": "flask", "version": "3.0.0", "vulns": []}]})
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, clean_json, ""),
    ):
        result = await check_dependencies(store_a, settings, repo_path=str(tmp_path))
    assert result["vulnerabilities"] == 0
    assert result["findings"] == []


# ---------- run_type_check ----------


async def test_run_type_check_mypy_no_errors(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("x: int = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, "Success: no issues found in 5 source files", ""),
    ):
        result = await run_type_check(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "mypy"
    assert result["errors"] == 0


async def test_run_type_check_mypy_with_errors(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("x: str = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, _MYPY_OUTPUT, ""),
    ):
        result = await run_type_check(store_a, settings, repo_path=str(tmp_path))
    assert result["errors"] == 1
    assert result["warnings"] == 1
    assert result["issues"][0]["file"] == "src/main.py"
    assert result["issues"][0]["severity"] == "error"


# ---------- analyze_complexity ----------


async def test_analyze_complexity_radon(store_a, settings, tmp_path):
    (tmp_path / "processor.py").write_text("def process_data(): pass\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, _RADON_JSON, ""),
    ):
        result = await analyze_complexity(store_a, settings, repo_path=str(tmp_path), threshold=10)
    assert result["tool"] == "radon"
    assert result["total_functions"] == 2
    assert result["above_threshold"] == 1
    assert result["hotspots"][0]["function"] == "process_data"
    assert result["hotspots"][0]["complexity"] == 18


async def test_analyze_complexity_above_threshold(store_a, settings, tmp_path):
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
        result = await analyze_complexity(store_a, settings, repo_path=str(tmp_path), threshold=10)
    assert result["above_threshold"] == 1
    assert result["hotspots"][0]["complexity"] == 25


# ---------- run_linter (JS/TS branch, fix, timeout) ----------

_ESLINT_JSON = json.dumps(
    [
        {
            "filePath": "src/app.js",
            "messages": [
                {"severity": 2, "line": 3, "column": 1, "ruleId": "no-unused-vars", "message": "x"},
                {"severity": 1, "line": 8, "column": 2, "ruleId": "semi", "message": "missing ;"},
            ],
        },
        {"filePath": "src/clean.js", "messages": []},
    ]
)


async def test_run_linter_javascript_eslint(store_a, settings, tmp_path):
    (tmp_path / "package.json").write_text('{"name": "app"}')
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, _ESLINT_JSON, ""),
    ):
        result = await run_linter(store_a, settings, repo_path=str(tmp_path))
    assert result["framework"] == "javascript"
    assert result["tool"] == "eslint"
    assert result["errors"] == 1  # severity>=2
    assert result["warnings"] == 1  # severity==1
    assert result["files_checked"] == 1  # only files with messages


async def test_run_linter_python_with_fix(store_a, settings, tmp_path):
    (tmp_path / "main.py").write_text("import os\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(0, "[]", "Found 3 errors. Fixed 3 errors."),
    ):
        result = await run_linter(store_a, settings, repo_path=str(tmp_path), fix=True)
    assert result["fixed"] == 3


async def test_run_linter_timeout(store_a, settings, tmp_path):
    import subprocess

    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=subprocess.TimeoutExpired(cmd="ruff", timeout=1),
    ):
        result = await run_linter(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "timeout"


# ---------- run_security_scan (npm audit branch, not found, timeout) ----------


async def test_run_security_scan_npm_audit(store_a, settings, tmp_path):
    (tmp_path / "package.json").write_text('{"name": "app"}')
    npm_json = json.dumps(
        {
            "vulnerabilities": {
                "lodash": {"severity": "high", "name": "lodash", "title": "Prototype pollution"},
                "minimist": {"severity": "moderate", "name": "minimist", "title": "ReDoS"},
                "leftpad": {"severity": "low", "name": "leftpad", "title": "Minor"},
            }
        }
    )
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, npm_json, ""),
    ):
        result = await run_security_scan(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "npm_audit"
    assert result["high"] == 1  # high counts as high
    assert result["medium"] == 1  # moderate -> medium
    assert result["low"] == 1
    assert result["total_issues"] == 3


async def test_run_security_scan_tool_not_found(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=FileNotFoundError("bandit not found"),
    ):
        result = await run_security_scan(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "tool_not_found"
    assert result["tool"] == "bandit"


async def test_run_security_scan_timeout(store_a, settings, tmp_path):
    import subprocess

    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=subprocess.TimeoutExpired(cmd="bandit", timeout=1),
    ):
        result = await run_security_scan(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "timeout"


# ---------- check_dependencies (safety fallback, npm, timeout) ----------


async def test_check_dependencies_safety_fallback(store_a, settings, tmp_path):
    """pip-audit missing -> falls back to safety."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
    safety_json = json.dumps([["requests", "<2.31", "2.25.0", "SSRF issue", "CVE-2023-1234"]])

    calls = {"n": 0}

    def _side_effect(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileNotFoundError("pip-audit not found")
        return (0, safety_json, "")

    with patch("src.tools.analysis_tool._run_subprocess", side_effect=_side_effect):
        result = await check_dependencies(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "safety"
    assert result["vulnerabilities"] == 1
    assert result["findings"][0]["package"] == "requests"


async def test_check_dependencies_npm(store_a, settings, tmp_path):
    (tmp_path / "package.json").write_text('{"name": "app"}')
    npm_json = json.dumps(
        {
            "vulnerabilities": {
                "lodash": {
                    "range": ">=4.0.0 <4.17.21",
                    "name": "lodash",
                    "title": "Prototype pollution",
                    "fixAvailable": {"version": "4.17.21"},
                }
            }
        }
    )
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, npm_json, ""),
    ):
        result = await check_dependencies(store_a, settings, repo_path=str(tmp_path))
    assert result["tool"] == "npm_audit"
    assert result["framework"] == "javascript"
    assert result["vulnerabilities"] == 1
    assert result["findings"][0]["fix_version"] == "4.17.21"


async def test_check_dependencies_timeout(store_a, settings, tmp_path):
    import subprocess

    (tmp_path / "pyproject.toml").write_text("[project]")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=subprocess.TimeoutExpired(cmd="pip-audit", timeout=1),
    ):
        result = await check_dependencies(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "timeout"


# ---------- run_type_check (tsc branch, not found, timeout) ----------


async def test_run_type_check_tsc(store_a, settings, tmp_path):
    (tmp_path / "package.json").write_text('{"name": "app"}')
    tsc_output = (
        "src/app.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
        "src/util.ts(3,1): warning TS6133: 'x' is declared but never used.\n"
    )
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        return_value=(1, tsc_output, ""),
    ):
        result = await run_type_check(store_a, settings, repo_path=str(tmp_path), framework="typescript")
    assert result["tool"] == "tsc"
    assert result["errors"] == 1
    assert result["warnings"] == 1
    assert result["issues"][0]["file"] == "src/app.ts"


async def test_run_type_check_tool_not_found(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=FileNotFoundError("mypy not found"),
    ):
        result = await run_type_check(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "tool_not_found"
    assert result["tool"] == "mypy"


async def test_run_type_check_timeout(store_a, settings, tmp_path):
    import subprocess

    (tmp_path / "app.py").write_text("x = 1\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=subprocess.TimeoutExpired(cmd="mypy", timeout=1),
    ):
        result = await run_type_check(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "timeout"


# ---------- analyze_complexity (JS grep branch, not found, timeout) ----------


async def test_analyze_complexity_javascript_grep(store_a, settings, tmp_path):
    (tmp_path / "package.json").write_text('{"name": "app"}')
    # Write a JS file with many branches so cc exceeds a low threshold.
    (tmp_path / "complex.js").write_text(
        "function f(){ if(a){} else if(b){} for(;;){} while(x){} "
        "if(c&&d||e){} switch(y){} try{}catch(z){} }\n"
    )
    result = await analyze_complexity(store_a, settings, repo_path=str(tmp_path), threshold=1)
    assert result["tool"] == "grep_count"
    assert result["total_functions"] >= 1
    assert result["above_threshold"] >= 1


async def test_analyze_complexity_tool_not_found(store_a, settings, tmp_path):
    (tmp_path / "app.py").write_text("def f(): pass\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=FileNotFoundError("radon not found"),
    ):
        result = await analyze_complexity(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "tool_not_found"
    assert result["tool"] == "radon"


async def test_analyze_complexity_timeout(store_a, settings, tmp_path):
    import subprocess

    (tmp_path / "app.py").write_text("def f(): pass\n")
    with patch(
        "src.tools.analysis_tool._run_subprocess",
        side_effect=subprocess.TimeoutExpired(cmd="radon", timeout=1),
    ):
        result = await analyze_complexity(store_a, settings, repo_path=str(tmp_path))
    assert result["error"] == "timeout"


# ---------- validation errors (empty repo_path) ----------


async def test_run_linter_missing_repo(store_a, settings):
    result = await run_linter(store_a, settings, repo_path="")
    assert result["error"] == "ValidationError"


async def test_run_security_scan_missing_repo(store_a, settings):
    result = await run_security_scan(store_a, settings, repo_path="")
    assert result["error"] == "ValidationError"


async def test_check_dependencies_missing_repo(store_a, settings):
    result = await check_dependencies(store_a, settings, repo_path="")
    assert result["error"] == "ValidationError"


async def test_run_type_check_missing_repo(store_a, settings):
    result = await run_type_check(store_a, settings, repo_path="")
    assert result["error"] == "ValidationError"


async def test_analyze_complexity_missing_repo(store_a, settings):
    result = await analyze_complexity(store_a, settings, repo_path="")
    assert result["error"] == "ValidationError"
