"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O roteamento compute é coberto por stubs
(sem tocar KB/DB); o roteamento tenant-scoped roda contra MySQL real via
`_route_tenant`/`_run_tenant`.
"""

from __future__ import annotations

import json

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import NAMESPACE, Settings
from src.server import mcp_server as M

from .conftest import TENANT_A, _test_settings, mint_token, patch_jwks, requires_mysql

# Funções puras compute roteadas por _route_compute (no namespace do módulo M).
_COMPUTE_FUNCS = [
    "get_agent_guidelines",
    "get_layer_policy",
    "get_forbidden_actions",
    "get_fallback_policy",
    "get_contract_change_policy",
    "get_final_response_template",
    "get_pre_execution_checklist",
    "search_governance_knowledge",
    "query_ecosystem_graph",
    "find_consumers_of",
    "find_dependencies_of",
    "get_service_metadata",
    "get_service_ownership",
    "get_service_dependencies",
    "get_port_map",
    "check_scope",
    "validate_lib_change",
    "validate_migration",
    "create_adr",
]

_COMPUTE_TOOLS = [n for n in M._TOOL_SCHEMAS if n not in M._TENANT_SCOPED_TOOLS and n != "status"]
_TENANT_TOOLS = sorted(M._TENANT_SCOPED_TOOLS)


def _settings(**over) -> Settings:
    return Settings(
        MCP_TWIN_AUDIENCE=f"mcp:{NAMESPACE}",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


class _DummyAudit:
    async def record(self, *a, **k) -> None:
        return None


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


@pytest.fixture()
def stub_compute(monkeypatch):
    """Stuba _get_repo + TODAS as funções compute (sem tocar KB/FS)."""
    monkeypatch.setattr(M, "_get_repo", lambda: object())
    for fn in _COMPUTE_FUNCS:
        monkeypatch.setattr(M, fn, lambda *a, **k: {"ok": True})
    return monkeypatch


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": NAMESPACE, "tools": len(M._TOOL_SCHEMAS)}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == set(M._TOOL_SCHEMAS.keys())
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["required_scope"].startswith(f"{NAMESPACE}:")
        assert t["capability"] == f"{NAMESPACE}.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    assert by_name["submit_suggestion"]["required_scope"].endswith(":write")
    assert by_name["update_suggestion_status"]["required_scope"].endswith(":write")
    assert by_name["create_adr"]["required_scope"].endswith(":write")
    assert by_name["get_layer_policy"]["required_scope"].endswith(":read")


# ── /mcp/tools/call — tool exempt (sem token) → compute status ────────────────
def test_call_exempt_status_without_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["status"] == "ok"
    assert payload["service"] == NAMESPACE


# ── /mcp/tools/call — PEP (RS256 real / stubs) ────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "get_port_map", "arguments": {}}})
    assert r.status_code == 401
    assert r.json()["error"] == "missing_twin_token"


def test_call_invalid_twin_token(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


def test_call_missing_jti_twin_token(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → verificador real rejeita (JTI_REQUIRED)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


def test_call_valid_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"status"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "status", "arguments": {}}})
    assert r.status_code == 403
    assert r.json()["error"] == "tool_excluded"


def test_call_unknown_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T", "jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "nope", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tool"


def test_call_compute_tool_runs_without_tenant_in_args(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T", "jti": "j"})
    captured: dict = {}

    def _spy(name, args):
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_run_compute", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    assert captured["name"] == "get_port_map"
    # compute NÃO é tenant-scoped → o tenant não é injetado nos args
    assert "tenant_id" not in captured["args"]


def test_call_tenant_tool_uses_tenant_from_claims(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})
    captured: dict = {}

    async def _spy(name, args, settings, tenant_id):
        captured.update(name=name, tenant_id=tenant_id, args=dict(args))
        return {"ok": True}

    monkeypatch.setattr(M, "_run_tenant", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "submit_suggestion",
                # tenant do cliente deve ser IGNORADO — usa o das claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "t"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "submit_suggestion"
    assert captured["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


def test_call_internal_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(_name, _args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_run_compute", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_port_map", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["tool"] == "get_port_map"


# ── _run_compute — status repo-free + roteia toda tool compute (stubs) ────────
def test_run_compute_status_is_repo_free():
    out = M._run_compute("status", {})
    assert out["status"] == "ok"
    assert out["service"] == NAMESPACE
    assert out["tools"] == len(M._TOOL_SCHEMAS)


@pytest.mark.parametrize("name", _COMPUTE_TOOLS)
def test_run_compute_routes_every_compute_tool(name, stub_compute):
    out = M._run_compute(name, {})
    assert out.get("ok") is True


def test_route_compute_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        M._route_compute("does_not_exist", {}, object())


def test_run_compute_graph_unavailable(stub_compute):
    stub_compute.setattr(M, "get_port_map", lambda *a, **k: (_ for _ in ()).throw(M.GraphUnavailable()))
    out = M._run_compute("get_port_map", {})
    assert out["error"] == "ecosystem_graph_unavailable"


def test_run_compute_validation_error(stub_compute):
    stub_compute.setattr(
        M, "get_layer_policy", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad layer"))
    )
    out = M._run_compute("get_layer_policy", {})
    assert out["error"] == "validation_error"
    assert "bad layer" in out["details"]


# ── _route_tenant — roteia toda tool tenant-scoped (stubs, sem DB) ────────────
@pytest.fixture()
def stub_tenant(monkeypatch):
    async def _ok(*a, **k):
        return {"ok": True, "input_summary": {}}

    for fn in (
        "submit_suggestion",
        "list_suggestions",
        "get_suggestion",
        "update_suggestion_status",
        "get_audit_log",
    ):
        monkeypatch.setattr(M, fn, _ok)
    # validate_agent_decision é SÍNCRONA no _route_tenant (compute + audit.record async).
    monkeypatch.setattr(M, "validate_agent_decision", lambda *a, **k: {"ok": True, "input_summary": {}})
    return monkeypatch


@pytest.mark.parametrize("name", _TENANT_TOOLS)
async def test_route_tenant_routes_every_tenant_tool(name, stub_tenant):
    out = await M._route_tenant(name, {}, object(), object(), _DummyAudit())
    assert out.get("ok") is True


async def test_route_tenant_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        await M._route_tenant("does_not_exist", {}, object(), object(), _DummyAudit())


async def test_route_tenant_validate_records_audit(monkeypatch):
    monkeypatch.setattr(
        M, "validate_agent_decision", lambda *a, **k: {"approved": True, "input_summary": {"x": 1}}
    )
    recorded: dict = {}

    class _Audit:
        async def record(self, result, summary=None):
            recorded["result"] = result
            recorded["summary"] = summary

    out = await M._route_tenant(
        "validate_agent_decision", {"repository_name": "r"}, object(), object(), _Audit()
    )
    assert out["approved"] is True
    assert recorded["result"] == out
    assert recorded["summary"] == {"x": 1}


async def test_route_tenant_audit_write_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(
        M, "validate_agent_decision", lambda *a, **k: {"approved": False, "input_summary": {}}
    )

    class _Audit:
        async def record(self, *a, **k):
            raise OSError("db down")

    out = await M._route_tenant(
        "validate_agent_decision", {"repository_name": "r"}, object(), object(), _Audit()
    )
    assert out["approved"] is False


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = Settings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


# ── _get_repo — singleton lazy (isolado de KB/FS) ─────────────────────────────
def test_get_repo_is_cached_singleton(monkeypatch):
    monkeypatch.setattr(M, "_repo", None)

    class _S:
        kb_path = "kb"

    calls = {"repo": 0}

    class _Repo:
        def __init__(self, **k):
            calls["repo"] += 1

    monkeypatch.setattr(M, "get_settings", lambda: _S())
    monkeypatch.setattr(M, "GovernanceRepository", _Repo)
    assert M._get_repo() is M._get_repo()
    assert calls["repo"] == 1


# ── build_server smoke (cobre a fábrica + configure + sidecar) ────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.delenv("MCP_TWIN_AUDIENCE", raising=False)
    from src.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == f"mcp:{NAMESPACE}"
    assert http_app.title.startswith("ai-governance-mcp")
    settings_mod.get_settings.cache_clear()


# ── Execução tenant-scoped (MySQL real) ───────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_route_tenant_routes_all_tools_on_mysql(repo, stores_a):
    suggestions, audit = stores_a

    async def rt(name, args):
        return await M._route_tenant(name, args, repo, suggestions, audit)

    created = await rt(
        "submit_suggestion",
        {
            "source_agent": "a",
            "target_repo": "platform-x",
            "category": "bug",
            "severity": "low",
            "title": "t",
            "description": "d",
        },
    )
    sid = created["suggestion"]["id"]
    assert (await rt("get_suggestion", {"suggestion_id": sid}))["found"] is True
    assert (await rt("list_suggestions", {}))["total"] >= 1
    assert "suggestion" in await rt(
        "update_suggestion_status", {"suggestion_id": sid, "new_status": "acknowledged"}
    )
    vad = await rt(
        "validate_agent_decision",
        {"repository_name": "r", "task_description": "t", "proposed_change": "p"},
    )
    assert "approved" in vad
    assert "entries" in await rt("get_audit_log", {})
    with pytest.raises(KeyError):
        await rt("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_run_tenant_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tenant -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> stores -> _route_tenant, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()
    created = await M._run_tenant(
        "submit_suggestion",
        {
            "source_agent": "a",
            "target_repo": "platform-x",
            "category": "bug",
            "severity": "low",
            "title": "t",
            "description": "d",
        },
        settings,
        TENANT_A,
    )
    assert created["suggestion"]["target_repo"] == "platform-x"
    listed = await M._run_tenant("list_suggestions", {}, settings, TENANT_A)
    assert listed["total"] == 1
    with pytest.raises(KeyError):
        await M._run_tenant("nope", {}, settings, TENANT_A)
