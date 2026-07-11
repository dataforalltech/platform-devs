"""Roteamento do `_dispatch` (async) + integridade do catálogo `_TOOL_SCHEMAS`.

As 10 tools compute-only roteiam com ``store=None`` (herméticas); as 4 tools de
persistência (scan_docs/audit_repo/get_audit_history/generate_doc_report) roteiam
contra MySQL real (@integration)."""

from __future__ import annotations

import pytest

from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch

from .conftest import requires_mysql

_EXPECTED_TOOLS = {
    "scan_docs",
    "search_docs",
    "get_doc_tree",
    "validate_doc",
    "check_links",
    "check_required_docs",
    "lint_markdown",
    "list_templates",
    "generate_doc",
    "check_doc_standards",
    "audit_repo",
    "find_stale_docs",
    "get_audit_history",
    "generate_doc_report",
}

_README = ("# Svc\n\n## Installation\n\nInstall it.\n\n## Usage\n\nUse it.\n") * 6
_CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial\n"


def _seed_repo(tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
    return tmp_path


# ── Schema / catálogo (sem dispatch) ──────────────────────────────────────────
def test_all_tools_registered():
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 14


def test_each_schema_has_description_and_object_type():
    for name, meta in _TOOL_SCHEMAS.items():
        assert "description" in meta, f"{name}: missing description"
        assert meta["schema"]["type"] == "object", f"{name}: schema type must be object"


def test_required_fields_in_properties():
    for name, meta in _TOOL_SCHEMAS.items():
        required = meta["schema"].get("required", [])
        props = meta["schema"].get("properties", {})
        for req_field in required:
            assert req_field in props, f"{name}: required field '{req_field}' not in properties"


# ── Dispatch hermético (compute-only, store=None) ─────────────────────────────
async def test_unknown_tool_raises_key_error(settings):
    with pytest.raises(KeyError):
        await _dispatch("does_not_exist", {}, settings, None)


async def test_list_templates_dispatch(settings):
    result = await _dispatch("list_templates", {}, settings, None)
    assert result["count"] == 6
    assert len(result["templates"]) == 6


async def test_check_required_docs_dispatch(settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch(
        "check_required_docs",
        {"repo_path": str(tmp_path), "standard": "standard"},
        settings,
        None,
    )
    assert "passed" in result
    assert "present" in result
    assert "missing" in result


async def test_scan_docs_dispatch_missing_repo(settings):
    result = await _dispatch("scan_docs", {}, settings, None)
    assert result["error"] == "ValidationError"


async def test_search_docs_dispatch_missing_query(settings, tmp_path):
    result = await _dispatch("search_docs", {"repo_path": str(tmp_path)}, settings, None)
    assert result["error"] == "ValidationError"


async def test_validate_doc_dispatch_missing_file(settings):
    result = await _dispatch("validate_doc", {}, settings, None)
    assert result["error"] == "ValidationError"


async def test_generate_doc_dispatch_invalid_template(settings):
    result = await _dispatch("generate_doc", {"template_name": "FAKE", "variables": {}}, settings, None)
    assert result["error"] == "ValidationError"


async def test_search_docs_dispatch_ok(settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch("search_docs", {"repo_path": str(tmp_path), "query": "Install"}, settings, None)
    assert result["total_matches"] >= 1


async def test_get_doc_tree_dispatch_ok(settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch("get_doc_tree", {"repo_path": str(tmp_path)}, settings, None)
    assert result["summary"]["total_files"] == 2


async def test_validate_doc_dispatch_ok(settings, tmp_path):
    f = tmp_path / "README.md"
    f.write_text(_README, encoding="utf-8")
    result = await _dispatch("validate_doc", {"file_path": str(f)}, settings, None)
    assert result["doc_type"] == "readme"


async def test_check_links_dispatch_ok(settings, tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# R\n\nSee [x](https://example.com)\n", encoding="utf-8")
    result = await _dispatch("check_links", {"file_path": str(f)}, settings, None)
    assert result["total_links"] == 1


async def test_lint_markdown_dispatch_ok(settings, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Title\n\n## Section\n\nContent.\n", encoding="utf-8")
    result = await _dispatch("lint_markdown", {"file_path": str(f)}, settings, None)
    assert result["passed"] is True


async def test_check_doc_standards_dispatch_ok(settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch("check_doc_standards", {"repo_path": str(tmp_path)}, settings, None)
    assert "overall_score" in result


async def test_find_stale_docs_dispatch_ok(settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch(
        "find_stale_docs", {"repo_path": str(tmp_path), "days_threshold": 5}, settings, None
    )
    assert "stale_count" in result


# ── Dispatch com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_get_audit_history_dispatch_empty(store_a, settings):
    result = await _dispatch("get_audit_history", {}, settings, store_a)
    assert result["total"] == 0
    assert result["audits"] == []


@pytest.mark.integration
@requires_mysql
async def test_scan_docs_dispatch_ok(store_a, settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch("scan_docs", {"repo_path": str(tmp_path)}, settings, store_a)
    assert result["total"] == 2


@pytest.mark.integration
@requires_mysql
async def test_audit_repo_dispatch_ok(store_a, settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch("audit_repo", {"repo_path": str(tmp_path)}, settings, store_a)
    assert "audit_id" in result


@pytest.mark.integration
@requires_mysql
async def test_generate_doc_report_dispatch_ok(store_a, settings, tmp_path):
    _seed_repo(tmp_path)
    result = await _dispatch("generate_doc_report", {"repo_path": str(tmp_path)}, settings, store_a)
    assert "score" in result
    assert "trend" in result
