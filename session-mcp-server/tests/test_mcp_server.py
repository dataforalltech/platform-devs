"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, tenant ausente, audiência errada, exempt, exclude,
unknown, internal_error, happy path) e _verify_inner_token (não configurado,
decode mockado e caminho real de audiência divergente).

O ``SessionStore`` é SQLite embarcado (hermético) — nenhum teste faz I/O de rede.
O PyJWKClient/JWKS é mockado; o único teste que decodifica de verdade gera um par
RSA local (sem rede).
"""

from __future__ import annotations

import json
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.config import settings as settings_mod
from src.config.settings import SessionSettings
from src.server import mcp_server as M

_AUD = "mcp:session-mcp"
_JWKS = "http://admin.local/.well-known/jwks.json"


def _settings() -> SessionSettings:
    return SessionSettings(MCP_TWIN_AUDIENCE=_AUD, URL_ADMIN_TWIN_JWKS=_JWKS)


@pytest.fixture()
def store():
    from src.db.store import SessionStore

    s = SessionStore(_settings())
    yield s
    s.close()


@pytest.fixture()
def client(store) -> TestClient:
    return TestClient(M._build_http_app(_settings(), store))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "session-mcp", "tools": len(M._TOOL_SCHEMAS)}


# ── /mcp/tools/list — 4 campos de policy por tool (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == set(M._TOOL_SCHEMAS)
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos / 2 ':')
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"session-mcp.{t['name']}"
        assert t["required_scope"].startswith("session-mcp:")
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas :read
    assert by_name["start_session"]["required_scope"].endswith(":write")
    assert by_name["complete_task"]["required_scope"].endswith(":write")
    assert by_name["submit_suggestion"]["required_scope"].endswith(":write")
    assert by_name["list_sessions"]["required_scope"].endswith(":read")
    assert by_name["get_task"]["required_scope"].endswith(":read")
    assert by_name["list_decisions"]["required_scope"].endswith(":read")
    # audit trail de decisões é domínio de governança
    assert by_name["list_decisions"]["data_domain"] == "governance"
    assert by_name["start_session"]["data_domain"] == "session"


def test_schema_invariants():
    assert set(M._POLICY_SPEC) == set(M._TOOL_SCHEMAS)
    for name, meta in M._TOOL_SCHEMAS.items():
        assert meta["description"], name
        assert meta["schema"]["type"] == "object", name


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_sessions", "arguments": {}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_twin_token"


# ── /mcp/tools/call — inner token inválido → 401 (fail-closed) ────────────────
def test_call_invalid_twin_token(client: TestClient, monkeypatch):
    def _boom(_tok, _settings):
        raise ValueError("bad signature")

    monkeypatch.setattr(M, "_verify_inner_token", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_sessions",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token válido injeta tenant das claims (INV-3) ───────────
def test_call_valid_token_injects_tenant_from_claims(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    def _spy(name, args, _store, _settings):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_sessions",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "list_sessions"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_sessions",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — happy path: token válido → executa e strippa tenant ─────
def test_call_valid_token_happy_path(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-1", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_sessions",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    # tenant_id injetado foi ignorado pelas tools → a tool executou com sucesso
    assert payload["count"] == 0
    assert payload["sessions"] == []


# ── /mcp/tools/call — start_session real deriva branch do input (happy path) ──
def test_call_start_session_derives_branch(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-1", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "start_session",
                "arguments": {"title": "T", "objective": "O", "repo": "platform-x"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["id"].startswith("sess_")
    assert payload["branch"].startswith("session/")
    assert payload["base_branch"] == "develop"


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"list_sessions"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_sessions", "arguments": {}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["count"] == 0


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"list_sessions"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_sessions", "arguments": {}}},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "tool_excluded"


# ── /mcp/tools/call — tool desconhecida → 404 ─────────────────────────────────
def test_call_unknown_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "nope", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tool"


# ── /mcp/tools/call — erro interno na tool → payload internal_error ────────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(name, args, _store, _settings):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_sessions",
                "arguments": {},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch: strip de tenant + KeyError ─────────────────────────────────────
def test_dispatch_strips_tenant_id(store):
    s = _settings()
    result = M._dispatch("list_sessions", {"tenant_id": "T"}, store, s)
    assert result["count"] == 0  # tenant_id não vira argumento inválido


def test_dispatch_unknown_raises_keyerror(store):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {}, store, _settings())


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = SessionSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── _verify_inner_token configurado usa PyJWKClient + jwt.decode (mockado) ─────
def test_verify_inner_token_decodes(monkeypatch):
    s = _settings()

    class _FakeKey:
        key = "K"

    class _FakeJWK:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _tok):
            return _FakeKey()

    captured: dict = {}

    def _decode(tok, key, algorithms, audience, options):
        captured.update(algorithms=algorithms, audience=audience, options=options)
        return {"tenant_id": "T", "jti": "j"}

    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWK)
    monkeypatch.setattr(M.jwt, "decode", _decode)
    claims = M._verify_inner_token("tok", s)
    assert claims["tenant_id"] == "T"
    assert captured["algorithms"] == ["RS256"]
    assert captured["audience"] == _AUD
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── audiência divergente: decode RS256 real (par RSA local) → 401 ─────────────
def _rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return priv, pub


def _issue(priv: bytes, aud: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"aud": aud, "jti": "j-1", "iat": now, "exp": now + 300, "tenant_id": "T-1"},
        priv,
        algorithm="RS256",
    )


def test_verify_wrong_audience_rejected(monkeypatch):
    """Token RS256 válido, mas aud != mcp:session-mcp → InvalidAudienceError."""
    priv, pub = _rsa_keypair()
    token = _issue(priv, aud="mcp:WRONG")

    class _Key:
        def __init__(self, pem):
            self.key = pem

    class _FakeJWK:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _tok):
            return _Key(pub)

    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWK)
    with pytest.raises(pyjwt.InvalidAudienceError):
        M._verify_inner_token(token, _settings())


def test_verify_correct_audience_accepts(monkeypatch):
    """Mesmo token com aud correta decodifica e devolve os claims (tenant)."""
    priv, pub = _rsa_keypair()
    token = _issue(priv, aud=_AUD)

    class _Key:
        def __init__(self, pem):
            self.key = pem

    class _FakeJWK:
        def __init__(self, _url):
            pass

        def get_signing_key_from_jwt(self, _tok):
            return _Key(pub)

    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWK)
    claims = M._verify_inner_token(token, _settings())
    assert claims["tenant_id"] == "T-1"
    assert claims["aud"] == _AUD


# ── _dispatch roteia TODAS as tools reais (saída derivada dos inputs) ─────────
def test_dispatch_routes_every_tool(store):
    s = _settings()

    def d(name, args):
        return M._dispatch(name, args, store, s)

    actor = {"type": "human", "id": "dev@dataforall.tech"}

    # sessão + branch + checkpoint + artifact + update
    sess = d("start_session", {"title": "T", "objective": "O", "repo": "platform-x"})
    sid = sess["id"]
    assert sess["branch"].startswith("session/")
    assert d("confirm_branch_created", {"session_id": sid, "sha": "abc"})["confirmed"] is True
    assert d("save_checkpoint", {"session_id": sid, "summary": "cp"})["session_id"] == sid
    assert d("add_artifact", {"session_id": sid, "artifact_type": "note", "content": "x"})["type"] == "note"
    assert d("update_session", {"session_id": sid, "status": "paused"})["status"] == "paused"
    assert d("list_sessions", {})["count"] >= 1
    assert d("get_session", {"session_id": sid})["id"] == sid
    assert "resume_hint" in d("resume_session", {"session_id": sid})

    # tasks: add / get / start / complete / fail / cancel / approve / list
    t = d("add_task", {"session_id": sid, "title": "t1"})
    assert d("get_task", {"task_id": t["id"]})["id"] == t["id"]
    assert d("start_task", {"task_id": t["id"]})["status"] == "in_progress"
    assert (
        d("complete_task", {"task_id": t["id"], "commit_sha": "s", "commit_message": "m"})["status"]
        == "completed"
    )
    t2 = d("add_task", {"session_id": sid, "title": "t2"})
    assert d("fail_task", {"task_id": t2["id"], "actor": actor, "reason": "boom"})["status"] == "failed"
    t3 = d("add_task", {"session_id": sid, "title": "t3"})
    assert d("cancel_task", {"task_id": t3["id"], "actor": actor, "reason": "drop"})["status"] == "cancelled"
    t4 = d("add_task", {"session_id": sid, "title": "t4", "needs_human_decision": True})
    assert d("approve_task", {"task_id": t4["id"], "decision": "go", "actor": actor})["decision"] == "go"
    assert d("list_tasks", {"session_id": sid})["count"] >= 1

    # service deps: add / list / remove
    assert d("add_service_dependency", {"session_id": sid, "service": "postgres"})["service"] == "postgres"
    assert d("list_service_dependencies", {"session_id": sid})["count"] == 1
    assert d("remove_service_dependency", {"session_id": sid, "service": "postgres"})["removed"] is True

    # suggestions: submit / list / get / accept / reject / defer / supersede
    sug = d("submit_suggestion", {"source_repo": "a", "target_repo": "platform-x", "title": "s1"})
    assert d("list_suggestions", {"target_repo": "platform-x"})["count"] >= 1
    assert d("get_suggestion", {"suggestion_id": sug["id"]})["id"] == sug["id"]
    accepted = d(
        "accept_suggestion",
        {"suggestion_id": sug["id"], "session_id": sid, "actor": actor},
    )
    assert accepted["suggestion"]["status"] == "accepted"
    r = d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "r"})
    assert (
        d("reject_suggestion", {"suggestion_id": r["id"], "actor": actor, "reason": "no"})["status"]
        == "rejected"
    )
    df = d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "d"})
    assert d("defer_suggestion", {"suggestion_id": df["id"], "actor": actor})["status"] == "deferred"
    o = d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "old"})
    n = d("submit_suggestion", {"source_repo": "a", "target_repo": "b", "title": "new"})
    sup = d("supersede_suggestion", {"suggestion_id": o["id"], "actor": actor, "by_suggestion_id": n["id"]})
    assert sup["status"] == "superseded"

    # decisions audit: list / get (a aprovação acima gravou uma decisão)
    decs = d("list_decisions", {"action": "approve_task"})
    assert decs["count"] >= 1
    assert d("get_decision", {"decision_id": decs["decisions"][0]["id"]})["decision"] == "go"

    # end_session roteia (a sessão ainda tem tasks abertas → open_tasks; branch coberto)
    ended = d("end_session", {"session_id": sid, "actor": actor, "rationale": "done"})
    assert ended.get("status") == "completed" or ended.get("error") == "open_tasks"


# ── build_server smoke (cobre a fábrica + stdio Server + sidecar) ─────────────
def test_build_server_smoke():
    settings_mod.get_settings.cache_clear()
    server, settings, store, http_app = M.build_server()
    try:
        assert server is not None
        assert settings.mcp_twin_audience == _AUD or settings.mcp_twin_audience == "mcp:session-mcp"
        assert http_app.title.startswith("session-mcp")
        resp = TestClient(http_app).get("/v1/health")
        assert resp.json()["service"] == "session-mcp"
    finally:
        store.close()
        settings_mod.get_settings.cache_clear()
