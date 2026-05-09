from __future__ import annotations

import pytest

from src.config.settings import QASettings
from src.db.store import QAStore
from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch

_EXPECTED_TOOLS = {
    "run_unit_tests",
    "run_e2e_tests",
    "run_api_tests",
    "generate_test_matrix",
    "screenshot_page",
    "check_accessibility",
    "visual_regression",
    "run_linter",
    "run_security_scan",
    "check_dependencies",
    "run_type_check",
    "analyze_complexity",
    "get_coverage_report",
    "generate_qa_report",
}


@pytest.fixture
def dispatch_store():
    s = QAStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def dispatch_settings():
    return QASettings(
        db_path=":memory:",
        screenshots_dir="/tmp/qa-test",
        baselines_dir="/tmp/qa-test-baselines",
        subprocess_timeout=10,
    )


# ---------- Schema tests ----------


def test_all_tools_registered():
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 14


def test_each_schema_has_description_and_type_object():
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


def test_dispatch_generate_qa_report_empty_store(dispatch_store, dispatch_settings):
    """Empty store → score 0, no crash."""
    result = _dispatch(
        "generate_qa_report",
        {"repo_path": "/empty/repo"},
        dispatch_settings,
        dispatch_store,
    )
    assert result["overall_score"] == 0
    assert result["grade"] == "F"
    assert "categories" in result
    assert "run_id" in result


def test_dispatch_run_unit_tests_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("run_unit_tests", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_run_api_tests_missing_base_url(dispatch_store, dispatch_settings):
    result = _dispatch(
        "run_api_tests",
        {"endpoints": []},
        dispatch_settings,
        dispatch_store,
    )
    assert result["error"] == "ValidationError"


def test_dispatch_generate_test_matrix_missing_base_url(dispatch_store, dispatch_settings):
    result = _dispatch(
        "generate_test_matrix",
        {"scenarios": []},
        dispatch_settings,
        dispatch_store,
    )
    assert result["error"] == "ValidationError"


def test_dispatch_run_linter_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("run_linter", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_run_security_scan_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("run_security_scan", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_check_dependencies_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("check_dependencies", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_run_type_check_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("run_type_check", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_analyze_complexity_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("analyze_complexity", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_get_coverage_report_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("get_coverage_report", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"


def test_dispatch_generate_qa_report_missing_repo(dispatch_store, dispatch_settings):
    result = _dispatch("generate_qa_report", {}, dispatch_settings, dispatch_store)
    assert result["error"] == "ValidationError"
