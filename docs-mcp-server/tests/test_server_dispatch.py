from __future__ import annotations

import pytest

from src.config.settings import DocsSettings
from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch

from .conftest import FakeDocsStore

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


@pytest.fixture
def dispatch_store():
    s = FakeDocsStore()
    yield s
    s.close()


@pytest.fixture
def dispatch_settings():
    return DocsSettings(
        stale_days_threshold=90,
        check_external_links=False,
        http_timeout=5.0,
    )


# ---------- Schema tests ----------


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


def test_unknown_tool_raises_key_error(dispatch_store, dispatch_settings):
    with pytest.raises(KeyError):
        _dispatch("does_not_exist", {}, dispatch_settings, dispatch_store)


# ---------- Dispatch tests ----------


def test_list_templates_dispatch(dispatch_store, dispatch_settings):
    """list_templates sem args → count=6."""
    result = _dispatch("list_templates", {}, dispatch_settings, dispatch_store)
    assert result["count"] == 6
    assert len(result["templates"]) == 6


def test_check_required_docs_dispatch(dispatch_store, dispatch_settings, tmp_path):
    """check_required_docs com tmp_repo → passed status presente."""
    (tmp_path / "README.md").write_text("# Readme\n\nContent\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial\n",
        encoding="utf-8",
    )

    result = _dispatch(
        "check_required_docs",
        {"repo_path": str(tmp_path), "standard": "standard"},
        dispatch_settings,
        dispatch_store,
    )

    assert "passed" in result
    assert "present" in result
    assert "missing" in result


def test_scan_docs_dispatch_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("scan_docs", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_search_docs_dispatch_missing_query(dispatch_store, dispatch_settings, tmp_path):
    result = _dispatch(
        "search_docs",
        {"repo_path": str(tmp_path)},
        dispatch_settings,
        dispatch_store,
    )
    assert result["error"] == "ValidationError"


def test_validate_doc_dispatch_missing_file(dispatch_store, dispatch_settings):
    result = _dispatch("validate_doc", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_generate_doc_dispatch_invalid_template(dispatch_store, dispatch_settings):
    result = _dispatch(
        "generate_doc",
        {"template_name": "FAKE", "variables": {}},
        dispatch_settings,
        dispatch_store,
    )
    assert result["error"] == "ValidationError"


def test_get_audit_history_dispatch_empty(dispatch_store, dispatch_settings):
    result = _dispatch("get_audit_history", {}, dispatch_settings, dispatch_store)
    assert result["total"] == 0
    assert result["audits"] == []


# ---------- Dispatch routing for every remaining tool ----------

_README = ("# Svc\n\n## Installation\n\nInstall it.\n\n## Usage\n\nUse it.\n") * 6
_CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial\n"


def _seed_repo(tmp_path):
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
    return tmp_path


def test_scan_docs_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch("scan_docs", {"repo_path": str(tmp_path)}, dispatch_settings, dispatch_store)
    assert result["total"] == 2


def test_search_docs_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch(
        "search_docs",
        {"repo_path": str(tmp_path), "query": "Install"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["total_matches"] >= 1


def test_get_doc_tree_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch("get_doc_tree", {"repo_path": str(tmp_path)}, dispatch_settings, dispatch_store)
    assert result["summary"]["total_files"] == 2


def test_validate_doc_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    f = tmp_path / "README.md"
    f.write_text(_README, encoding="utf-8")
    result = _dispatch("validate_doc", {"file_path": str(f)}, dispatch_settings, dispatch_store)
    assert result["doc_type"] == "readme"


def test_check_links_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# R\n\nSee [x](https://example.com)\n", encoding="utf-8")
    result = _dispatch("check_links", {"file_path": str(f)}, dispatch_settings, dispatch_store)
    assert result["total_links"] == 1


def test_lint_markdown_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Title\n\n## Section\n\nContent.\n", encoding="utf-8")
    result = _dispatch("lint_markdown", {"file_path": str(f)}, dispatch_settings, dispatch_store)
    assert result["passed"] is True


def test_check_doc_standards_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch("check_doc_standards", {"repo_path": str(tmp_path)}, dispatch_settings, dispatch_store)
    assert "overall_score" in result


def test_audit_repo_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch("audit_repo", {"repo_path": str(tmp_path)}, dispatch_settings, dispatch_store)
    assert "audit_id" in result


def test_find_stale_docs_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch(
        "find_stale_docs",
        {"repo_path": str(tmp_path), "days_threshold": 5},
        dispatch_settings,
        dispatch_store,
    )
    assert "stale_count" in result


def test_generate_doc_report_dispatch_ok(dispatch_store, dispatch_settings, tmp_path):
    _seed_repo(tmp_path)
    result = _dispatch("generate_doc_report", {"repo_path": str(tmp_path)}, dispatch_settings, dispatch_store)
    assert "score" in result
    assert "trend" in result
