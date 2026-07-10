"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, tenant ausente, exclude,
unknown, happy path, erro interno), _verify_inner_token (não configurado,
decode real com RS256, audiência errada) e o roteamento de _dispatch.

O PyJWKClient/JWKS é sempre mockado (chave RSA gerada no teste) e o PostgreSQL é
substituído pelo _FakePool do conftest — os testes nunca fazem I/O de rede/DB.
"""

from __future__ import annotations

import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.config.settings import QASettings
from src.db.store import QAStore
from src.server import mcp_server as M

_ALL_TOOLS = {
    "status",
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
_TOOL_FUNCS = _ALL_TOOLS - {"status"}


def _settings() -> QASettings:
    return QASettings(
        mcp_twin_audience="mcp:qa-mcp",
        url_admin_twin_jwks="http://admin.local/.well-known/jwks.json",
        db_path=":memory:",
        screenshots_dir="/tmp/qa-test",
        baselines_dir="/tmp/qa-test-baselines",
        subprocess_timeout=5,
    )


@pytest.fixture()
def http_store() -> QAStore:
    s = QAStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture()
def client(http_store: QAStore) -> TestClient:
    return TestClient(M._build_http_app(_settings(), http_store))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "service": "qa-mcp", "tools": len(M._TOOL_SCHEMAS)}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == _ALL_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos → 2 ':')
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"qa-mcp.{t['name']}"
        assert t["required_scope"].startswith("qa-mcp:")
    by_name = {t["name"]: t for t in tools}
    # execuções/geração usam verbo :write; análises/relatórios :read
    assert by_name["run_unit_tests"]["required_scope"].endswith(":write")
    assert by_name["screenshot_page"]["required_scope"].endswith(":write")
    assert by_name["run_linter"]["required_scope"].endswith(":read")
    assert by_name["generate_qa_report"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_qa_report", "arguments": {"repo_path": "/r"}}},
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
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/r"},
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

    def _spy(name, args, _settings, _store):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"repo_path": "/r", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "generate_qa_report"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/r"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — happy path: token válido → executa (store real fake) ─────
def test_call_valid_token_happy_path(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-1", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/empty/repo"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["overall_score"] == 0
    assert payload["grade"] == "F"


# ── /mcp/tools/call — tool exempt (status) sem token → 200 ────────────────────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["service"] == "qa-mcp"
    assert payload["tools"] == len(M._TOOL_SCHEMAS)


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"generate_qa_report"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "generate_qa_report", "arguments": {"repo_path": "/r"}}},
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


# ── /mcp/tools/call — erro interno na tool → payload internal_error ───────────
def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(name, args, _settings, _store):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "generate_qa_report",
                "arguments": {"repo_path": "/r"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch — status + KeyError + roteamento de todas as tools ──────────────
def test_dispatch_status(http_store: QAStore):
    out = M._dispatch("status", {}, _settings(), http_store)
    assert out["service"] == "qa-mcp"
    assert out["status"] == "ok"


def test_dispatch_unknown_raises(http_store: QAStore):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {}, _settings(), http_store)


def test_dispatch_routes_every_tool(http_store: QAStore, monkeypatch):
    """Cada branch de _dispatch encaminha para a função-tool correspondente."""
    sentinel = {"routed": True}
    for fn in _TOOL_FUNCS:
        monkeypatch.setattr(M, fn, lambda *a, **k: sentinel)
    s = _settings()
    for name in _TOOL_FUNCS:
        assert M._dispatch(name, {}, s, http_store) is sentinel, name


def test_dispatch_forwards_kwargs(http_store: QAStore, monkeypatch):
    """Verifica que os argumentos do cliente chegam como kwargs à tool."""
    captured: dict = {}

    def _spy(_store, _settings, **kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(M, "run_unit_tests", _spy)
    M._dispatch(
        "run_unit_tests",
        {"repo_path": "/r", "framework": "pytest", "coverage": True},
        _settings(),
        http_store,
    )
    assert captured["repo_path"] == "/r"
    assert captured["framework"] == "pytest"
    assert captured["coverage"] is True


# ── _verify_inner_token ───────────────────────────────────────────────────────
def _rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


class _FakeSigningKey:
    def __init__(self, pub_pem: bytes) -> None:
        self.key = pub_pem


class _FakeJWKClient:
    _pub: bytes = b""

    def __init__(self, _url: str) -> None:
        pass

    def get_signing_key_from_jwt(self, _tok: str):
        return _FakeSigningKey(self._pub)


def test_verify_inner_token_unconfigured():
    s = QASettings(mcp_twin_audience="", url_admin_twin_jwks="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_decodes_valid(monkeypatch):
    priv, pub = _rsa_keypair()
    token = jwt.encode(
        {"aud": "mcp:qa-mcp", "jti": "abc", "exp": 9999999999, "tenant_id": "T-9"},
        priv,
        algorithm="RS256",
    )
    _FakeJWKClient._pub = pub
    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWKClient)
    claims = M._verify_inner_token(token, _settings())
    assert claims["tenant_id"] == "T-9"
    assert claims["jti"] == "abc"


def test_verify_inner_token_wrong_audience(monkeypatch):
    priv, pub = _rsa_keypair()
    token = jwt.encode(
        {"aud": "mcp:WRONG", "jti": "abc", "exp": 9999999999, "tenant_id": "T"},
        priv,
        algorithm="RS256",
    )
    _FakeJWKClient._pub = pub
    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWKClient)
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(token, _settings())


def test_verify_inner_token_missing_jti(monkeypatch):
    priv, pub = _rsa_keypair()
    token = jwt.encode(
        {"aud": "mcp:qa-mcp", "exp": 9999999999, "tenant_id": "T"},
        priv,
        algorithm="RS256",
    )
    _FakeJWKClient._pub = pub
    monkeypatch.setattr(M.jwt, "PyJWKClient", _FakeJWKClient)
    with pytest.raises(jwt.MissingRequiredClaimError):
        M._verify_inner_token(token, _settings())


# ── build_server + main (http-only) ───────────────────────────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", _settings)
    server, settings, store, http_app = M.build_server()
    try:
        assert server is not None
        assert settings.mcp_twin_audience == "mcp:qa-mcp"
        assert http_app.title.startswith("qa-mcp")
        resp = TestClient(http_app).get("/v1/health")
        assert resp.json()["service"] == "qa-mcp"
    finally:
        store.close()


def test_main_http_only(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_ONLY", "1")
    monkeypatch.setattr(M, "get_settings", _settings)
    called: dict = {}

    import uvicorn

    def _fake_run(app, **kwargs):
        called["port"] = kwargs.get("port")

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    M.main()
    assert called["port"] == 7100
