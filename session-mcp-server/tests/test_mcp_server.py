"""Testes do servidor MCP (dispatch, schemas, handlers HTTP e MCP).

Hermeticos: usam um SessionStore in-memory (SQLite), sem rede. Cobrem o roteamento
de _dispatch para cada ferramenta, os invariantes de schema/escopo e os handlers
assíncronos list_tools/call_tool.
"""

from __future__ import annotations

import json

import pytest

from src.config.settings import SessionSettings
from src.db.store import SessionStore
from src.server.mcp_server import (
    _TOOL_SCHEMAS,
    SCOPE_FOR_TOOL,
    SCOPES_SUPPORTED,
    _build_http_app,
    _dispatch,
    _JSONEncoder,
    build_server,
)

_ACTOR = {"type": "human", "id": "dev@dataforall.tech"}


@pytest.fixture
def store() -> SessionStore:
    s = SessionStore(SessionSettings())
    yield s
    s.close()


@pytest.fixture
def session_id(store: SessionStore) -> str:
    result = _dispatch(
        "start_session",
        {"title": "T", "objective": "O", "repo": "platform-x"},
        store,
        "develop",
    )
    return result["id"]


# ── Schemas & scopes ─────────────────────────────────────────────────────── #


class TestSchemaInvariants:
    def test_scope_keys_match_tool_keys(self):
        assert set(SCOPE_FOR_TOOL) == set(_TOOL_SCHEMAS)

    def test_every_scope_is_supported(self):
        assert set(SCOPE_FOR_TOOL.values()) <= set(SCOPES_SUPPORTED)

    def test_every_schema_has_description_and_schema(self):
        for name, meta in _TOOL_SCHEMAS.items():
            assert meta["description"], name
            assert meta["schema"]["type"] == "object", name


class TestJSONEncoder:
    def test_encodes_datetime_and_decimal(self):
        from datetime import date, datetime
        from decimal import Decimal

        payload = {"dt": datetime(2020, 1, 1), "d": date(2021, 2, 3), "num": Decimal("1.5")}
        text = json.dumps(payload, cls=_JSONEncoder)
        loaded = json.loads(text)
        assert loaded["dt"].startswith("2020-01-01")
        assert loaded["d"] == "2021-02-03"
        assert loaded["num"] == 1.5

    def test_falls_back_for_unknown_type(self):
        class Weird:
            pass

        with pytest.raises(TypeError):
            json.dumps({"x": Weird()}, cls=_JSONEncoder)


# ── HTTP health app ──────────────────────────────────────────────────────── #


class TestHttpApp:
    def test_build_http_app_has_health_route(self):
        app = _build_http_app()
        paths = {r.path for r in app.routes}
        assert "/v1/health" in paths


# ── _dispatch routing (one path per tool) ────────────────────────────────── #


class TestDispatchSessions:
    def test_start_session(self, store):
        result = _dispatch(
            "start_session",
            {"title": "T", "objective": "O", "repo": "platform-x"},
            store,
            "develop",
        )
        assert result["id"].startswith("sess_")
        assert result["branch"].startswith("session/")

    def test_confirm_branch_created(self, store, session_id):
        result = _dispatch("confirm_branch_created", {"session_id": session_id}, store, "develop")
        assert result["confirmed"] is True

    def test_save_checkpoint(self, store, session_id):
        result = _dispatch(
            "save_checkpoint",
            {"session_id": session_id, "summary": "cp", "context": {"k": "v"}},
            store,
            "develop",
        )
        assert result["session_id"] == session_id

    def test_update_session(self, store, session_id):
        result = _dispatch(
            "update_session", {"session_id": session_id, "status": "paused"}, store, "develop"
        )
        assert result["status"] == "paused"

    def test_add_artifact(self, store, session_id):
        result = _dispatch(
            "add_artifact",
            {"session_id": session_id, "artifact_type": "note", "content": "x"},
            store,
            "develop",
        )
        assert result["type"] == "note"

    def test_list_sessions(self, store, session_id):
        result = _dispatch("list_sessions", {}, store, "develop")
        assert result["count"] >= 1

    def test_get_session(self, store, session_id):
        result = _dispatch("get_session", {"session_id": session_id}, store, "develop")
        assert result["id"] == session_id

    def test_resume_session(self, store, session_id):
        result = _dispatch("resume_session", {"session_id": session_id}, store, "develop")
        assert "resume_hint" in result

    def test_end_session(self, store, session_id):
        result = _dispatch(
            "end_session",
            {"session_id": session_id, "actor": _ACTOR, "rationale": "done"},
            store,
            "develop",
        )
        assert result["status"] == "completed"


class TestDispatchTasks:
    def _add_task(self, store, session_id, **kw):
        return _dispatch("add_task", {"session_id": session_id, **kw}, store, "develop")

    def test_add_and_get_task(self, store, session_id):
        task = self._add_task(store, session_id, title="t")
        got = _dispatch("get_task", {"task_id": task["id"]}, store, "develop")
        assert got["id"] == task["id"]

    def test_start_task(self, store, session_id):
        task = self._add_task(store, session_id, title="t")
        result = _dispatch("start_task", {"task_id": task["id"]}, store, "develop")
        assert result["status"] == "in_progress"

    def test_complete_task(self, store, session_id):
        task = self._add_task(store, session_id, title="t")
        result = _dispatch(
            "complete_task",
            {"task_id": task["id"], "commit_sha": "abc", "commit_message": "m"},
            store,
            "develop",
        )
        assert result["status"] == "completed"

    def test_fail_task(self, store, session_id):
        task = self._add_task(store, session_id, title="t")
        result = _dispatch(
            "fail_task",
            {"task_id": task["id"], "actor": _ACTOR, "reason": "nope"},
            store,
            "develop",
        )
        assert result["status"] == "failed"

    def test_cancel_task(self, store, session_id):
        task = self._add_task(store, session_id, title="t")
        result = _dispatch(
            "cancel_task",
            {"task_id": task["id"], "actor": _ACTOR, "reason": "drop"},
            store,
            "develop",
        )
        assert result["status"] == "cancelled"

    def test_approve_task(self, store, session_id):
        task = self._add_task(store, session_id, title="t", needs_human_decision=True)
        result = _dispatch(
            "approve_task",
            {"task_id": task["id"], "decision": "go", "actor": _ACTOR},
            store,
            "develop",
        )
        assert result["decision"] == "go"

    def test_list_tasks(self, store, session_id):
        self._add_task(store, session_id, title="t")
        result = _dispatch("list_tasks", {"session_id": session_id}, store, "develop")
        assert result["count"] == 1


class TestDispatchServiceDeps:
    def test_add_list_remove(self, store, session_id):
        added = _dispatch(
            "add_service_dependency",
            {"session_id": session_id, "service": "postgres", "role": "db"},
            store,
            "develop",
        )
        assert added["service"] == "postgres"
        listed = _dispatch(
            "list_service_dependencies", {"session_id": session_id}, store, "develop"
        )
        assert listed["count"] == 1
        removed = _dispatch(
            "remove_service_dependency",
            {"session_id": session_id, "service": "postgres"},
            store,
            "develop",
        )
        assert removed["removed"] is True


class TestDispatchSuggestions:
    def test_submit_list_get(self, store):
        submitted = _dispatch(
            "submit_suggestion",
            {"source_repo": "a", "target_repo": "b", "title": "s"},
            store,
            "develop",
        )
        sid = submitted["id"]
        listed = _dispatch("list_suggestions", {"target_repo": "b"}, store, "develop")
        assert listed["count"] == 1
        got = _dispatch("get_suggestion", {"suggestion_id": sid}, store, "develop")
        assert got["id"] == sid

    def test_accept(self, store, session_id):
        submitted = _dispatch(
            "submit_suggestion",
            {"source_repo": "a", "target_repo": "platform-x", "title": "s"},
            store,
            "develop",
        )
        result = _dispatch(
            "accept_suggestion",
            {"suggestion_id": submitted["id"], "session_id": session_id, "actor": _ACTOR},
            store,
            "develop",
        )
        assert result["suggestion"]["status"] == "accepted"

    def test_reject(self, store):
        submitted = _dispatch(
            "submit_suggestion",
            {"source_repo": "a", "target_repo": "b", "title": "s"},
            store,
            "develop",
        )
        result = _dispatch(
            "reject_suggestion",
            {"suggestion_id": submitted["id"], "actor": _ACTOR, "reason": "dup"},
            store,
            "develop",
        )
        assert result["status"] == "rejected"

    def test_defer(self, store):
        submitted = _dispatch(
            "submit_suggestion",
            {"source_repo": "a", "target_repo": "b", "title": "s"},
            store,
            "develop",
        )
        result = _dispatch(
            "defer_suggestion",
            {"suggestion_id": submitted["id"], "actor": _ACTOR},
            store,
            "develop",
        )
        assert result["status"] == "deferred"

    def test_supersede(self, store):
        s1 = _dispatch(
            "submit_suggestion",
            {"source_repo": "a", "target_repo": "b", "title": "old"},
            store,
            "develop",
        )
        s2 = _dispatch(
            "submit_suggestion",
            {"source_repo": "a", "target_repo": "b", "title": "new"},
            store,
            "develop",
        )
        result = _dispatch(
            "supersede_suggestion",
            {"suggestion_id": s1["id"], "actor": _ACTOR, "by_suggestion_id": s2["id"]},
            store,
            "develop",
        )
        assert result["status"] == "superseded"


class TestDispatchDecisions:
    def test_list_and_get_decision(self, store, session_id):
        task = _dispatch(
            "add_task",
            {"session_id": session_id, "title": "t", "needs_human_decision": True},
            store,
            "develop",
        )
        _dispatch(
            "approve_task",
            {"task_id": task["id"], "decision": "go", "actor": _ACTOR, "rationale": "ok"},
            store,
            "develop",
        )
        listed = _dispatch("list_decisions", {"action": "approve_task"}, store, "develop")
        assert listed["count"] == 1
        d_id = listed["decisions"][0]["id"]
        got = _dispatch("get_decision", {"decision_id": d_id}, store, "develop")
        assert got["id"] == d_id


class TestDispatchErrors:
    def test_unknown_tool_raises_keyerror(self, store):
        with pytest.raises(KeyError):
            _dispatch("does_not_exist", {}, store, "develop")


# ── Async handlers via build_server ──────────────────────────────────────── #


class TestBuildServer:
    def test_build_server_returns_components(self):
        server, settings, built_store, http_app = build_server()
        try:
            assert server is not None
            assert settings is not None
            paths = {r.path for r in http_app.routes}
            assert "/v1/health" in paths
            # MCP HTTP endpoints wired
            assert "/mcp/tools/list" in paths
            assert "/mcp/tools/call" in paths
        finally:
            built_store.close()

    def test_http_mcp_endpoints_exercise_async_handlers(self):
        """Cobre os handlers async list_tools/call_tool via os endpoints HTTP MCP."""
        from fastapi.testclient import TestClient

        _server, _settings, built_store, http_app = build_server()
        try:
            client = TestClient(http_app)

            listed = client.get("/mcp/tools/list").json()
            names = {t["name"] for t in listed["result"]["tools"]}
            assert "start_session" in names
            assert len(names) == len(_TOOL_SCHEMAS)

            called = client.post(
                "/mcp/tools/call",
                json={
                    "params": {
                        "name": "start_session",
                        "arguments": {
                            "title": "T",
                            "objective": "O",
                            "repo": "platform-x",
                        },
                    }
                },
            ).json()
            content = called["result"]["content"][0]["text"]
            payload = json.loads(content)
            assert payload["id"].startswith("sess_")
        finally:
            built_store.close()

    def test_http_mcp_call_unknown_tool_returns_error(self):
        """A ferramenta inexistente cai no ramo KeyError -> unknown_tool."""
        from fastapi.testclient import TestClient

        _server, _settings, built_store, http_app = build_server()
        try:
            client = TestClient(http_app)
            called = client.post(
                "/mcp/tools/call",
                json={"params": {"name": "does_not_exist", "arguments": {}}},
            ).json()
            payload = json.loads(called["result"]["content"][0]["text"])
            assert payload["error"] == "unknown_tool"
        finally:
            built_store.close()

    def test_http_mcp_call_internal_error_is_caught(self):
        """Um erro inesperado dentro do dispatch vira internal_error (não propaga)."""
        from fastapi.testclient import TestClient

        _server, _settings, built_store, http_app = build_server()
        try:
            client = TestClient(http_app)
            # approve_task com decision inválida -> ValueError no store -> internal_error
            called = client.post(
                "/mcp/tools/call",
                json={
                    "params": {
                        "name": "start_session",
                        "arguments": {"title": "", "objective": "", "repo": ""},
                    }
                },
            ).json()
            payload = json.loads(called["result"]["content"][0]["text"])
            # title/objective/repo vazios -> ValidationError da própria tool
            assert payload["error"] == "ValidationError"
        finally:
            built_store.close()
