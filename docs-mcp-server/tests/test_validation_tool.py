from __future__ import annotations

from src.tools.validation_tool import (
    check_links,
    check_required_docs,
    lint_markdown,
    validate_doc,
)

_README_VALID = (
    "# My Service\n\n"
    "## Installation\n\n"
    "Run `pip install my-service` to get started.\n\n"
    "## Usage\n\n"
    "Import and use the client.\n" * 10
)

_CHANGELOG_VALID = (
    "# Changelog\n\n"
    "## [Unreleased]\n\n"
    "## [1.0.0] - 2026-01-01\n\n"
    "### Added\n- Initial\n"
)


def test_validate_readme_valid(store, settings, tmp_path):
    f = tmp_path / "README.md"
    f.write_text(_README_VALID, encoding="utf-8")

    result = validate_doc(store, settings, file_path=str(f))

    assert result["doc_type"] == "readme"
    assert result["valid"] is True
    errors = [i for i in result["issues"] if i["severity"] == "error"]
    assert len(errors) == 0


def test_validate_readme_missing_section(store, settings, tmp_path):
    f = tmp_path / "README.md"
    f.write_text(
        "# My Service\n\n## Installation\n\nInstall with pip.\n" * 10,
        encoding="utf-8",
    )

    result = validate_doc(store, settings, file_path=str(f))

    errors = [i for i in result["issues"] if i["severity"] == "error"]
    assert any("Usage" in i["message"] for i in errors)
    assert result["valid"] is False


def test_validate_changelog_valid(store, settings, tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(_CHANGELOG_VALID, encoding="utf-8")

    result = validate_doc(store, settings, file_path=str(f))

    assert result["doc_type"] == "changelog"
    errors = [i for i in result["issues"] if i["severity"] == "error"]
    assert len(errors) == 0


def test_validate_changelog_missing_unreleased(store, settings, tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(
        "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial\n",
        encoding="utf-8",
    )

    result = validate_doc(store, settings, file_path=str(f))

    errors = [i for i in result["issues"] if i["severity"] == "error"]
    assert any("Unreleased" in i["message"] for i in errors)


def test_validate_adr_auto_detect(store, settings, tmp_path):
    f = tmp_path / "ADR-001.md"
    adr_content = (
        "# ADR-001: Use SQLite\n\n"
        "**Status:** accepted\n\n"
        "## Context\n\nWe need a simple DB.\n\n"
        "## Decision\n\nUse SQLite for local storage.\n\n"
        "## Consequences\n\nSimple setup.\n\n"
        "## Status\n\nAccepted.\n"
    )
    f.write_text(adr_content, encoding="utf-8")

    result = validate_doc(store, settings, file_path=str(f), doc_type="auto")

    assert result["doc_type"] == "adr"


def test_validate_doc_file_not_found(store, settings):
    result = validate_doc(store, settings, file_path="/nonexistent/file.md")
    assert result["error"] == "ValidationError"


def test_check_links_valid_internal(store, settings, tmp_path):
    target = tmp_path / "guide.md"
    target.write_text("# Guide\n\nContent\n", encoding="utf-8")
    doc = tmp_path / "README.md"
    doc.write_text("# Readme\n\nSee [guide](guide.md)\n", encoding="utf-8")

    result = check_links(store, settings, file_path=str(doc))

    assert result["broken"] == 0
    assert result["valid"] >= 1


def test_check_links_broken_internal(store, settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# Readme\n\nSee [missing](missing-file.md)\n", encoding="utf-8")

    result = check_links(store, settings, file_path=str(doc))

    assert result["broken"] == 1
    assert result["issues"][0]["type"] == "internal"


def test_check_links_anchor_valid(store, settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text(
        "# Readme\n\nSee [installation](#installation)\n\n## Installation\n\nContent\n",
        encoding="utf-8",
    )

    result = check_links(store, settings, file_path=str(doc))

    assert result["broken"] == 0


def test_check_links_external_not_checked_by_default(store, settings, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# Readme\n\nSee [link](https://example.com)\n", encoding="utf-8")

    result = check_links(store, settings, file_path=str(doc))

    # External links not checked by default → counted as valid
    assert result["broken"] == 0
    assert result["total_links"] == 1


def test_check_required_docs_standard_pass(store, settings, tmp_repo):
    result = check_required_docs(store, settings, repo_path=str(tmp_repo), standard="standard")

    assert result["passed"] is True
    assert "README.md" in result["present"]
    assert "CHANGELOG.md" in result["present"]
    assert result["missing"] == []


def test_check_required_docs_full_missing(store, settings, tmp_repo):
    result = check_required_docs(store, settings, repo_path=str(tmp_repo), standard="full")

    assert "AGENTS.md" in result["missing"]
    assert result["passed"] is False


def test_check_required_docs_invalid_standard(store, settings, tmp_repo):
    result = check_required_docs(store, settings, repo_path=str(tmp_repo), standard="invalid")
    assert result["error"] == "ValidationError"


def test_lint_markdown_no_issues(store, settings, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(
        "# Title\n\n## Section One\n\nContent here.\n\n## Section Two\n\nMore content.\n",
        encoding="utf-8",
    )

    result = lint_markdown(store, settings, file_path=str(f))

    assert result["errors"] == 0
    assert result["warnings"] == 0
    assert result["passed"] is True


def test_lint_markdown_heading_skip(store, settings, tmp_path):
    f = tmp_path / "doc.md"
    # h1 → h3 skips h2
    f.write_text("# Title\n\n### Subsection\n\nContent.\n", encoding="utf-8")

    result = lint_markdown(store, settings, file_path=str(f))

    heading_skip_issues = [i for i in result["issues"] if i["rule"] == "heading-skip"]
    assert len(heading_skip_issues) >= 1


def test_lint_markdown_unclosed_codeblock(store, settings, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Title\n\n```python\nprint('hello')\n", encoding="utf-8")

    result = lint_markdown(store, settings, file_path=str(f))

    unclosed = [i for i in result["issues"] if i["rule"] == "unclosed-codeblock"]
    assert len(unclosed) == 1
    assert result["errors"] >= 1
    assert result["passed"] is False


def test_lint_markdown_missing_h1(store, settings, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("## Section\n\nContent without h1.\n", encoding="utf-8")

    result = lint_markdown(store, settings, file_path=str(f))

    missing_h1 = [i for i in result["issues"] if i["rule"] == "missing-h1"]
    assert len(missing_h1) == 1
