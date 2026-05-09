from __future__ import annotations

from src.tools.standards_tool import check_doc_standards

_README_CONTENT = (
    "# Test Service\n\n"
    "## Installation\n\n"
    "Run pip install to get started with this service.\n\n"
    "## Usage\n\n"
    "Import and use the client in your code.\n"
) * 5

_CHANGELOG_CONTENT = (
    "# Changelog\n\n"
    "## [Unreleased]\n\n"
    "## [1.0.0] - 2026-01-01\n\n"
    "### Added\n- Initial release of the service\n"
)


def test_check_doc_standards_full_pass(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README_CONTENT, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG_CONTENT, encoding="utf-8")

    result = check_doc_standards(store, settings, repo_path=str(tmp_path), standard="standard")

    assert "overall_score" in result
    assert result["overall_score"] > 0
    assert "grade" in result
    assert "categories" in result
    assert "completeness" in result["categories"]
    assert "validity" in result["categories"]
    assert "quality" in result["categories"]


def test_check_doc_standards_missing_docs(store, settings, tmp_path):
    # No docs created — completeness should be low
    result = check_doc_standards(store, settings, repo_path=str(tmp_path), standard="standard")

    assert "overall_score" in result
    completeness = result["categories"]["completeness"]["score"]
    assert completeness == 0


def test_check_doc_standards_grade_calculation(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(_README_CONTENT, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG_CONTENT, encoding="utf-8")

    result = check_doc_standards(store, settings, repo_path=str(tmp_path), standard="standard")

    score = result["overall_score"]
    grade = result["grade"]

    if score >= 90:
        assert grade == "A"
    elif score >= 75:
        assert grade == "B"
    elif score >= 60:
        assert grade == "C"
    elif score >= 40:
        assert grade == "D"
    else:
        assert grade == "F"


def test_check_doc_standards_returns_recommendations(store, settings, tmp_path):
    # Only README, missing CHANGELOG → should have recommendations for standard level
    readme = (
        "# Service\n\n## Installation\n\nInstall it.\n\n## Usage\n\nUse it.\n"
    ) * 8
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")

    result = check_doc_standards(store, settings, repo_path=str(tmp_path), standard="standard")

    assert "recommendations" in result
    assert isinstance(result["recommendations"], list)


def test_check_doc_standards_invalid_repo(store, settings):
    result = check_doc_standards(store, settings, repo_path="/nonexistent/path")
    assert result["error"] == "ValidationError"
