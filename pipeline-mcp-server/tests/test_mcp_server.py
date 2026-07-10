"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (4 campos de policy por tool), /mcp/tools/call
(missing/invalid/wrong-audience token, tenant estrito das claims, exempt, exclude,
unknown, happy path, erro interno), _verify_inner_token (não configurado + decode +
audiência errada), o roteamento de _dispatch para as 14 tools e o build_server.

Tudo é HERMÉTICO: o PyJWKClient/JWKS e o PipelineStore são mockados; nenhum teste
faz I/O de rede/DB (FID-01 / Test Doubles Policy).
"""

from __future__ import annotations

import json

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import PipelineSettings
from src.server import mcp_server as M

from .conftest import FakePipelineStore

_EXPECTED_TOOLS = {
    # pipeline
    "register_pipeline",
    "get_pipeline",
    "list_pipeline",
    "promote_service",
    "approve_promotion",
    "watch_prs",
    "block_service",
    "rollback",
    # gates
    "add_gate_result",
    "get_gate_status",
    "clear_gates",
    # history / config
    "get_promotion_history",
    "get_pipeline_overview",
    "set_pipeline_config",
}


def _settings() -> PipelineSettings:
    return PipelineSettings(
        MCP_TWIN_AUDIENCE="mcp:pipeline-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
        github_token="",
        github_org="",
    )


@pytest.fixture()
def store() -> FakePipelineStore:
    s = FakePipelineStore()
    s.register_pipeline("svc-a", "test-org/svc-a")
    return s


@pytest.fixture()
def client(store: FakePipelineStore) -> TestClient:
    return TestClient(M._build_http_app(store, _settings()))


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "pipeline-mcp", "tools": 14}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert "properties" in t["inputSchema"]
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"pipeline-mcp.{t['name']}"
        assert t["required_scope"].startswith("pipeline-mcp:")
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas :read
    assert by_name["promote_service"]["required_scope"].endswith(":write")
    assert by_name["approve_promotion"]["required_scope"].endswith(":write")
    assert by_name["add_gate_result"]["required_scope"].endswith(":write")
    assert by_name["get_pipeline"]["required_scope"].endswith(":read")
    assert by_name["get_gate_status"]["required_scope"].endswith(":read")
    assert by_name["get_promotion_history"]["required_scope"].endswith(":read")


def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 14


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required {required - props} fora de properties"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_pipeline", "arguments": {"service": "svc-a"}}},
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
                "name": "get_pipeline",
                "arguments": {"service": "svc-a"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — audiência errada → 401 (defense in depth) ───────────────
def test_call_wrong_audience_rejected(client: TestClient, monkeypatch):
    def _wrong_aud(_tok, _settings):
        raise jwt.InvalidAudienceError("Audience doesn't match")

    monkeypatch.setattr(M, "_verify_inner_token", _wrong_aud)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_pipeline",
                "arguments": {"service": "svc-a"},
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
                "name": "get_pipeline",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"service": "svc-a", "tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "get_pipeline"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_pipeline",
                "arguments": {"service": "svc-a"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — happy path: token válido → executa a tool real ──────────
def test_call_valid_token_happy_path(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-1", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "get_pipeline",
                "arguments": {"service": "svc-a"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    # tenant_id injetado é ignorado pela tool (não está no schema) → executa OK
    assert payload["service"] == "svc-a"


# ── /mcp/tools/call — tool exempt (sem token) via monkeypatch ─────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"get_pipeline_overview"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_pipeline_overview", "arguments": {}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["total_services"] == 1


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_pipeline"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_pipeline", "arguments": {"service": "svc-a"}}},
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
                "name": "get_pipeline",
                "arguments": {"service": "svc-a"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert "kaboom" in payload["detail"]


# ── _dispatch cobre as 14 tools + KeyError ────────────────────────────────────
def test_dispatch_routes_all_tools():
    s = _settings()
    store = FakePipelineStore()
    store.register_pipeline("svc-a", "test-org/svc-a")

    def d(name, args):
        return M._dispatch(name, args, s, store)

    assert d("register_pipeline", {"service": "n", "repo": "o/n"})["action"] == "created"
    assert d("get_pipeline", {"service": "svc-a"})["service"] == "svc-a"
    assert d("list_pipeline", {})["total"] >= 1
    assert (
        d("promote_service", {"service": "svc-a", "from_env": "dev", "to_env": "homol", "promoted_by": "u"})[
            "can_promote"
        ]
        is False
    )
    assert d("approve_promotion", {"promotion_id": 999, "approved_by": "a"})["error"] == "not_found"
    assert d("watch_prs", {})["error"] == "github_not_configured"
    assert d("block_service", {"service": "svc-a", "reason": "r", "blocked_by": "a"})["blocked"]
    # rollback exige serviço não bloqueado → usa outro serviço registrado
    d("register_pipeline", {"service": "svc-r", "repo": "o/r"})
    assert (
        d("rollback", {"service": "svc-r", "env": "prod", "to_version": "v1", "rolled_back_by": "ops"})[
            "rolled_back"
        ]
        is True
    )
    assert (
        d("add_gate_result", {"service": "svc-a", "env": "dev", "gate_type": "qa_tests", "passed": True})[
            "gate_recorded"
        ]
        is True
    )
    assert "can_promote" in d("get_gate_status", {"service": "svc-a", "env": "homol"})
    assert d("clear_gates", {"service": "svc-a", "env": "dev"})["cleared"] is True
    assert d("get_promotion_history", {})["limit"] == 20
    assert d("get_pipeline_overview", {})["total_services"] >= 1
    assert (
        d("set_pipeline_config", {"service": "svc-a", "gates_required": {"homol": ["qa_tests"]}})["updated"]
        is True
    )
    with pytest.raises(KeyError):
        d("does_not_exist", {})


def test_dispatch_register_uses_default_base_branch():
    s = _settings()
    store = FakePipelineStore()
    result = M._dispatch("register_pipeline", {"service": "n2", "repo": "o/n2"}, s, store)
    assert result["pipeline"]["base_branch"] == "develop"


def test_dispatch_get_promotion_history_respects_limit():
    s = _settings()
    store = FakePipelineStore()
    result = M._dispatch("get_promotion_history", {"limit": 5}, s, store)
    assert result["limit"] == 5


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = PipelineSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="", github_token="", github_org="")
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
    assert captured["audience"] == "mcp:pipeline-mcp"
    assert set(captured["options"]["require"]) == {"exp", "aud", "jti"}


# ── build_server smoke (fábrica + stdio Server; store/settings faked) ─────────
def test_build_server_smoke(monkeypatch):
    fake = FakePipelineStore()
    fake.register_pipeline("svc-a", "test-org/svc-a")
    monkeypatch.setattr(M, "PipelineStore", lambda *a, **k: fake)
    monkeypatch.setattr(M, "get_settings", lambda: PipelineSettings(github_token="", github_org=""))
    server, store, settings, http_app = M.build_server()
    assert server is not None
    assert isinstance(store, FakePipelineStore)
    assert settings.mcp_twin_audience == "mcp:pipeline-mcp"
    assert http_app.title.startswith("pipeline-mcp")
    # health continua acessível no http_app retornado
    resp = TestClient(http_app).get("/v1/health")
    assert resp.json()["service"] == "pipeline-mcp"
