from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config.settings import QASettings
from src.db.store import QAStore
from src.server import mcp_server
from src.server.mcp_server import (
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    _build_http_app,
    _dispatch,
    build_server,
)

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
            assert req_field in props, f"{name}: required field '{req_field}' not in properties"


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


# ---------- Scope map coverage ----------


def test_scope_map_covers_all_tools():
    assert set(SCOPE_FOR_TOOL.keys()) == _EXPECTED_TOOLS
    assert set(SCOPE_FOR_TOOL.values()) <= {"qa:read", "qa:write"}


# ---------- Dispatch happy-path forwarding ----------
# Each branch of _dispatch forwards to its tool with the right kwargs; we patch
# the tool symbol imported into mcp_server and assert the forwarding contract.

_SENTINEL = {"ok": True}


def _patch_tool(name):
    return patch.object(mcp_server, name, return_value=_SENTINEL)


def test_dispatch_run_unit_tests_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("run_unit_tests") as m:
        result = _dispatch(
            "run_unit_tests",
            {"repo_path": "/r", "framework": "pytest", "coverage": True},
            dispatch_settings,
            dispatch_store,
        )
    assert result is _SENTINEL
    _, kwargs = m.call_args
    assert kwargs["repo_path"] == "/r"
    assert kwargs["framework"] == "pytest"
    assert kwargs["coverage"] is True


def test_dispatch_run_e2e_tests_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("run_e2e_tests") as m:
        result = _dispatch(
            "run_e2e_tests",
            {"test_path": "/t", "base_url": "http://x", "browser": "firefox"},
            dispatch_settings,
            dispatch_store,
        )
    assert result is _SENTINEL
    assert m.call_args.kwargs["browser"] == "firefox"


def test_dispatch_run_api_tests_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("run_api_tests") as m:
        result = _dispatch(
            "run_api_tests",
            {"base_url": "http://x", "endpoints": [{"path": "/a"}]},
            dispatch_settings,
            dispatch_store,
        )
    assert result is _SENTINEL
    assert m.call_args.kwargs["endpoints"] == [{"path": "/a"}]


def test_dispatch_generate_test_matrix_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("generate_test_matrix") as m:
        result = _dispatch(
            "generate_test_matrix",
            {"base_url": "http://x", "scenarios": [{"name": "s", "endpoint": "/e"}]},
            dispatch_settings,
            dispatch_store,
        )
    assert result is _SENTINEL
    assert m.call_args.kwargs["scenarios"][0]["name"] == "s"


def test_dispatch_screenshot_page_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("screenshot_page") as m:
        _dispatch(
            "screenshot_page",
            {"url": "http://x", "viewport": "mobile", "selector": "nav"},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["viewport"] == "mobile"
    assert m.call_args.kwargs["selector"] == "nav"


def test_dispatch_check_accessibility_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("check_accessibility") as m:
        _dispatch(
            "check_accessibility",
            {"url": "http://x", "standard": "WCAG2AAA"},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["standard"] == "WCAG2AAA"


def test_dispatch_visual_regression_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("visual_regression") as m:
        _dispatch(
            "visual_regression",
            {"url": "http://x", "baseline_name": "home", "threshold_pct": 5.0},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["baseline_name"] == "home"
    assert m.call_args.kwargs["threshold_pct"] == 5.0


def test_dispatch_run_linter_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("run_linter") as m:
        _dispatch(
            "run_linter",
            {"repo_path": "/r", "fix": True},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["fix"] is True


def test_dispatch_run_security_scan_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("run_security_scan") as m:
        _dispatch(
            "run_security_scan",
            {"repo_path": "/r", "framework": "python"},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["framework"] == "python"


def test_dispatch_check_dependencies_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("check_dependencies") as m:
        _dispatch("check_dependencies", {"repo_path": "/r"}, dispatch_settings, dispatch_store)
    assert m.call_args.kwargs["repo_path"] == "/r"


def test_dispatch_run_type_check_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("run_type_check") as m:
        _dispatch(
            "run_type_check",
            {"repo_path": "/r", "framework": "typescript"},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["framework"] == "typescript"


def test_dispatch_analyze_complexity_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("analyze_complexity") as m:
        _dispatch(
            "analyze_complexity",
            {"repo_path": "/r", "threshold": 15},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["threshold"] == 15


def test_dispatch_get_coverage_report_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("get_coverage_report") as m:
        _dispatch(
            "get_coverage_report",
            {"repo_path": "/r", "framework": "python"},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["repo_path"] == "/r"


def test_dispatch_generate_qa_report_forwards(dispatch_store, dispatch_settings):
    with _patch_tool("generate_qa_report") as m:
        _dispatch(
            "generate_qa_report",
            {"repo_path": "/r", "last_n_runs": 3},
            dispatch_settings,
            dispatch_store,
        )
    assert m.call_args.kwargs["last_n_runs"] == 3


# ---------- HTTP app + build_server ----------


def test_build_http_app_health():
    app = _build_http_app()
    routes = {getattr(r, "path", None) for r in app.routes}
    assert "/v1/health" in routes
    # Invoke the health handler directly.
    health_fn = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/v1/health")
    assert health_fn() == {"status": "ok", "service": "qa-mcp"}


def test_build_server_returns_components(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_settings", lambda: QASettings(db_path=":memory:"))
    server, settings, store, http_app = build_server()
    try:
        assert server is not None
        assert settings is not None
        assert http_app is not None
    finally:
        store.close()
