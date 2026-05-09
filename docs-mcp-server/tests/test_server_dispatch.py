from __future__ import annotations

import pytest

from src.config.settings import DocsSettings
from src.db.store import DocsStore
from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch

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
    s = DocsStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def dispatch_settings():
    return DocsSettings(
        db_path=":memory:",
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
            assert req_field in props, (
                f"{name}: required field '{req_field}' not in properties"
            )


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
