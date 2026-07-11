"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (happy
path / dispatch / unknown) roda contra MySQL real via `_run_tool`/`_dispatch`.
"""

from __future__ import annotations

import json

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import SessionSettings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

_EXPECTED_TOOLS = {
    "start_session",
    "confirm_branch_created",
    "save_checkpoint",
    "update_session",
    "add_artifact",
    "list_sessions",
    "get_session",
    "resume_session",
    "end_session",
    "add_task",
    "approve_task",
    "start_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    "list_tasks",
    "get_task",
    "add_service_dependency",
    "list_service_dependencies",
    "remove_service_dependency",
    "submit_suggestion",
    "list_suggestions",
    "get_suggestion",
    "accept_suggestion",
    "reject_suggestion",
    "defer_suggestion",
    "supersede_suggestion",
    "list_decisions",
    "get_decision",
}


def _settings(**over) -> SessionSettings:
    return SessionSettings(
        MCP_TWIN_AUDIENCE="mcp:session-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 29
    assert set(M._TOOL_SCHEMAS) == _EXPECTED_TOOLS


def test_schema_policy_invariants():
    assert set(M._POLICY_SPEC) == set(M._TOOL_SCHEMAS)
    for name, meta in M._TOOL_SCHEMAS.items():
        assert meta["description"], name
        assert meta["schema"]["type"] == "object", name
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "session-mcp", "tools": 29}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"session-mcp.{t['name']}"
        assert t["required_scope"].startswith("session-mcp:")
    by_name = {t["name"]: t for t in tools}
    assert by_name["start_session"]["required_scope"].endswith(":write")
    assert by_name["list_sessions"]["required_scope"].endswith(":read")
    assert by_name["get_task"]["required_scope"].endswith(":read")
    # audit trail de decisões é domínio de governança
    assert by_name["list_decisions"]["data_domain"] == "governance"
    assert by_name["start_session"]["data_domain"] == "session"


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "list_sessions", "arguments": {}}})
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_sessions", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_sessions", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_sessions", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"list_sessions"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "list_sessions", "arguments": {}}})
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = SessionSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


# ── stdio call_tool → recusa fail-closed (gateway-only) + smoke ───────────────
def test_build_server_stdio_and_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert settings.mcp_twin_audience == "mcp:session-mcp"
    assert http_app.title.startswith("session-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "session-mcp"


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_tools(store_a):
    s = _settings()

    async def d(name, args):
        return await M._dispatch(name, args, s, store_a)

    sess = await d("start_session", {"title": "T", "objective": "O", "repo": "platform-x"})
    sid = sess["id"]
    assert sess["branch"].startswith("session/")
    assert (await d("confirm_branch_created", {"session_id": sid, "sha": "abc"}))["confirmed"] is True
    assert (await d("save_checkpoint", {"session_id": sid, "summary": "cp"}))["session_id"] == sid
    assert (await d("add_artifact", {"session_id": sid, "artifact_type": "note", "content": "x"}))[
        "type"
    ] == "note"
    assert (await d("update_session", {"session_id": sid, "status": "paused"}))["status"] == "paused"
    assert (await d("list_sessions", {}))["count"] >= 1
    assert (await d("get_session", {"session_id": sid}))["id"] == sid
    assert "resume_hint" in await d("resume_session", {"session_id": sid})

    t = await d("add_task", {"session_id": sid, "title": "t1"})
    assert (await d("get_task", {"task_id": t["id"]}))["id"] == t["id"]
    assert (await d("start_task", {"task_id": t["id"]}))["status"] == "in_progress"
    assert (await d("complete_task", {"task_id": t["id"], "commit_sha": "s", "commit_message": "m"}))[
        "status"
    ] == "completed"
    assert (await d("list_tasks", {"session_id": sid}))["count"] >= 1

    actor = {"type": "human", "id": "dev@dataforall.tech"}
    assert (await d("add_service_dependency", {"session_id": sid, "service": "postgres"}))[
        "service"
    ] == "postgres"
    assert (await d("list_service_dependencies", {"session_id": sid}))["count"] == 1
    assert (await d("remove_service_dependency", {"session_id": sid, "service": "postgres"}))[
        "removed"
    ] is True

    sug = await d("submit_suggestion", {"source_repo": "a", "target_repo": "platform-x", "title": "s1"})
    assert (await d("list_suggestions", {"target_repo": "platform-x"}))["count"] >= 1
    assert (await d("get_suggestion", {"suggestion_id": sug["id"]}))["id"] == sug["id"]
    accepted = await d("accept_suggestion", {"suggestion_id": sug["id"], "session_id": sid, "actor": actor})
    assert accepted["suggestion"]["status"] == "accepted"

    r = await d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "r"})
    assert (await d("reject_suggestion", {"suggestion_id": r["id"], "actor": actor, "reason": "no"}))[
        "status"
    ] == "rejected"
    df = await d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "d"})
    assert (await d("defer_suggestion", {"suggestion_id": df["id"], "actor": actor}))["status"] == "deferred"
    o = await d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "old"})
    n = await d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "new"})
    sup = await d(
        "supersede_suggestion", {"suggestion_id": o["id"], "actor": actor, "by_suggestion_id": n["id"]}
    )
    assert sup["status"] == "superseded"

    t4 = await d("add_task", {"session_id": sid, "title": "t4", "needs_human_decision": True})
    assert (await d("approve_task", {"task_id": t4["id"], "decision": "go", "actor": actor}))[
        "decision"
    ] == "go"
    decs = await d("list_decisions", {"action": "approve_task"})
    assert decs["count"] >= 1
    assert (await d("get_decision", {"decision_id": decs["decisions"][0]["id"]}))["decision"] == "go"

    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> SessionStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    result = await M._run_tool(
        "start_session", {"title": "T", "objective": "O", "repo": "o/e2e"}, settings, TENANT_A
    )
    assert result["id"].startswith("sess_")
    got = await M._run_tool("get_session", {"session_id": result["id"]}, settings, TENANT_A)
    assert got["id"] == result["id"]
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)


@pytest.mark.integration
@requires_mysql
async def test_http_call_happy_path(seed_platforms, monkeypatch, rsa_key):
    """Full stack HTTP: PEP RS256 real -> _run_tool credencial-zero -> MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    patch_jwks(monkeypatch, rsa_key)
    client = TestClient(M._build_http_app(_test_settings()))
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "start_session",
                "arguments": {"title": "T", "objective": "O", "repo": "platform-x"},
                "_meta": {"twin_token": mint_token(rsa_key, tenant_id=TENANT_A)},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["id"].startswith("sess_")
    assert payload["branch"].startswith("session/")
