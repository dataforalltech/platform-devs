"""Tools de relatório (async) contra MySQL real (§16 / FID-02).

`generate_qa_report` lê o histórico REAL do store (tenant-scoped); `get_coverage_report`
lê coverage.json de um tmp_path e persiste no store real."""

from __future__ import annotations

import json

import pytest

from src.tools.report_tool import generate_qa_report, get_coverage_report

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]

_COVERAGE_JSON = json.dumps(
    {
        "totals": {
            "covered_lines": 820,
            "num_statements": 1000,
        },
        "files": {
            "src/main.py": {"summary": {"covered_lines": 95, "num_statements": 100}},
            "src/utils.py": {"summary": {"covered_lines": 62, "num_statements": 100}},
        },
    }
)


# ---------- get_coverage_report ----------


async def test_get_coverage_report_python(store_a, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    cov_json = tmp_path / "coverage.json"
    cov_json.write_text(_COVERAGE_JSON)

    result = await get_coverage_report(store_a, settings, repo_path=str(tmp_path))
    assert result["framework"] == "python"
    assert result["overall_pct"] == 82.0
    assert result["lines_covered"] == 820
    assert result["lines_total"] == 1000
    assert result["meets_threshold"] is True  # 82 >= 80
    assert len(result["modules"]) == 2


async def test_get_coverage_report_below_threshold(store_a, settings, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    low_cov = json.dumps(
        {
            "totals": {"covered_lines": 50, "num_statements": 100},
            "files": {},
        }
    )
    cov_json = tmp_path / "coverage.json"
    cov_json.write_text(low_cov)
    settings = settings.model_copy(update={"coverage_threshold": 80.0})

    result = await get_coverage_report(store_a, settings, repo_path=str(tmp_path))
    assert result["meets_threshold"] is False
    assert result["overall_pct"] == 50.0


# ---------- generate_qa_report ----------


async def _insert_run(store, run_type, status, summary, repo_path="/repo"):
    await store.save_run(
        run_type=run_type,
        status=status,
        summary=summary,
        details={},
        repo_path=repo_path,
    )


async def test_generate_qa_report_with_history(store_a, settings):
    repo = "/my/repo"
    await _insert_run(store_a, "unit", "passed", {"passed": 10, "failed": 0, "errors": 0}, repo)
    await _insert_run(store_a, "security", "passed", {"high": 0, "medium": 0, "low": 2}, repo)
    await _insert_run(store_a, "linter", "passed", {"errors": 0, "warnings": 1}, repo)
    await _insert_run(store_a, "coverage", "passed", {"overall_pct": 85.0}, repo)
    await _insert_run(store_a, "dependencies", "passed", {"vulnerabilities": 0}, repo)

    result = await generate_qa_report(store_a, settings, repo_path=repo)
    assert result["overall_score"] > 0
    assert result["grade"] in ("A", "B", "C", "D", "F")
    assert "categories" in result
    assert "unit" in result["categories"]
    assert "run_id" in result


async def test_generate_qa_report_empty_history(store_a, settings):
    result = await generate_qa_report(store_a, settings, repo_path="/nonexistent/repo")
    assert result["overall_score"] == 0
    assert result["grade"] == "F"
    for cat in ("unit", "security", "linter", "coverage", "dependencies"):
        assert result["categories"][cat]["summary"] == "no data"


async def test_generate_qa_report_grade_A(store_a, settings):
    repo = "/perfect/repo"
    await _insert_run(store_a, "unit", "passed", {"passed": 20, "failed": 0, "errors": 0}, repo)
    await _insert_run(store_a, "security", "passed", {"high": 0, "medium": 0, "low": 0}, repo)
    await _insert_run(store_a, "linter", "passed", {"errors": 0, "warnings": 0}, repo)
    await _insert_run(store_a, "coverage", "passed", {"overall_pct": 95.0}, repo)
    await _insert_run(store_a, "dependencies", "passed", {"vulnerabilities": 0}, repo)

    result = await generate_qa_report(store_a, settings, repo_path=repo)
    assert result["overall_score"] >= 90
    assert result["grade"] == "A"


async def test_generate_qa_report_grade_F(store_a, settings):
    repo = "/bad/repo"
    await _insert_run(store_a, "unit", "failed", {"passed": 0, "failed": 10, "errors": 0}, repo)
    await _insert_run(store_a, "security", "failed", {"high": 10, "medium": 5, "low": 2}, repo)
    await _insert_run(store_a, "linter", "failed", {"errors": 20, "warnings": 10}, repo)
    await _insert_run(store_a, "coverage", "failed", {"overall_pct": 10.0}, repo)
    await _insert_run(store_a, "dependencies", "failed", {"vulnerabilities": 5}, repo)

    result = await generate_qa_report(store_a, settings, repo_path=repo)
    assert result["overall_score"] < 40
    assert result["grade"] == "F"
