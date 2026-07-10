"""Testes do sidecar mcp_http + PEP inner-token (STD-MCP-001 / STD-SEC-006).

Cobre: /v1/health, /mcp/tools/list (campos de policy), /mcp/tools/call
(missing/invalid token, exempt, tenant das claims, exclude, unknown),
_verify_inner_token não configurado, _dispatch (rota das 24 tools) e os handlers
stdio de build_server. O PyJWKClient/JWKS é sempre mockado — os testes nunca fazem
I/O de rede (Test Doubles Policy). O GitHubClient (backend) também é mockado.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import DeploySettings
from src.server import mcp_server as M

_EXPECTED_TOOLS = {
    # git
    "list_repos",
    "create_branch",
    "list_branches",
    "commit_files",
    # pr
    "create_pr",
    "get_pr",
    "merge_pr",
    "list_prs",
    # workflow
    "trigger_workflow",
    "list_workflow_runs",
    "get_workflow_run",
    "cancel_workflow_run",
    # deploy
    "deploy",
    "get_deploy_status",
    # pipeline
    "scaffold_pipeline",
    "get_pipeline_templates",
    # acr
    "setup_repo",
    "acr_build",
    "list_acr_images",
    # healthcheck
    "ensure_all_repos_healthy",
    # local workspace
    "get_repos_root",
    "set_repos_root",
    "list_local_repos",
    "clone_repo",
}


def _settings() -> DeploySettings:
    return DeploySettings(
        github_token="test_token_ghp_xxx",
        github_org="test-org",
        MCP_TWIN_AUDIENCE="mcp:deploy-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
    )


@pytest.fixture()
def client() -> TestClient:
    # GitHubClient mockado — nenhuma chamada real à API/rede.
    return TestClient(M._build_http_app(_settings(), MagicMock()))


@pytest.fixture()
def gh_client() -> MagicMock:
    # Backend mockado para os testes de roteamento do _dispatch (tools stubadas).
    return MagicMock()


# ── /v1/health ────────────────────────────────────────────────────────────────
def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "deploy-mcp", "tools": 24}


# ── /mcp/tools/list — todos os 4 campos de policy (CI-2) ──────────────────────
def test_tools_list_has_policy_fields(client: TestClient):
    r = client.get("/mcp/tools/list")
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        # required_scope no formato dominio:tipo:acao (3 segmentos)
        assert t["required_scope"].count(":") == 2
        assert t["required_scope"].startswith("deploy-mcp:")
        assert t["capability"] == f"deploy-mcp.{t['name']}"
    by_name = {t["name"]: t for t in tools}
    # geradores/mutadores usam verbo :write; consultas :read
    assert by_name["deploy"]["required_scope"].endswith(":write")
    assert by_name["merge_pr"]["required_scope"].endswith(":write")
    assert by_name["list_repos"]["required_scope"].endswith(":read")
    assert by_name["get_deploy_status"]["required_scope"].endswith(":read")


def test_tools_list_count():
    assert len(M._TOOL_SCHEMAS) == 24
    assert set(M._TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_required_fields_are_in_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        schema = meta["schema"]
        props = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        assert not (required - props), f"{name}: required fora de properties"


# ── /mcp/tools/call — sem inner token → 401 ───────────────────────────────────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_twin_token"


# ── /mcp/tools/call — inner token inválido → 401 (fail-closed) ─────────────────
def test_call_invalid_twin_token(client: TestClient, monkeypatch):
    def _boom(_tok, _settings):
        raise ValueError("bad signature")

    monkeypatch.setattr(M, "_verify_inner_token", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_repos",
                "arguments": {},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_twin_token"


# ── /mcp/tools/call — token válido injeta tenant das claims (INV-3) ────────────
def test_call_valid_token_injects_tenant_from_claims(client: TestClient, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T-42", "jti": "j"})

    def _spy(name, args, settings, client):  # assinatura do _dispatch do deploy
        captured["name"] = name
        captured["args"] = dict(args)
        return {"ok": True}

    monkeypatch.setattr(M, "_dispatch", _spy)
    r = client.post(
        "/mcp/tools/call",
        json={
            "params": {
                "name": "list_repos",
                # tenant do cliente deve ser IGNORADO/sobrescrito pelas claims
                "arguments": {"tenant_id": "ATTACKER"},
                "_meta": {"twin_token": "tok"},
            }
        },
    )
    assert r.status_code == 200
    assert captured["name"] == "list_repos"
    assert captured["args"]["tenant_id"] == "T-42"  # das claims, não "ATTACKER"


# ── /mcp/tools/call — token sem tenant nas claims → 401 ───────────────────────
def test_call_valid_token_without_tenant(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"jti": "j"})
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "missing_tenant_scope"


# ── /mcp/tools/call — tool exempt (sem token) ─────────────────────────────────
def test_call_exempt_tool_without_token(client: TestClient, monkeypatch):
    # deploy-mcp não tem exempt por default; exercita o branch tokenless.
    monkeypatch.setattr(M, "_EXEMPT_TOOLS", frozenset({"get_pipeline_templates"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_pipeline_templates", "arguments": {}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert "templates" in json.loads(text)


# ── /mcp/tools/call — denylist (exclude) → 403 ────────────────────────────────
def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_pipeline_templates"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_pipeline_templates", "arguments": {}}},
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


# ── /mcp/tools/call — exceção interna vira payload internal_error (200) ────────
def test_call_internal_error_payload(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": "T"})

    def _boom(name, args, settings, client):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_dispatch", _boom)
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}, "_meta": {"twin_token": "t"}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert "internal_error" in text and "kaboom" in text


# ── _verify_inner_token não configurado → PermissionError (fail-closed) ────────
def test_verify_inner_token_unconfigured():
    s = DeploySettings(github_token="t", MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


# ── _verify_inner_token — round-trip RS256 real (JWKS mockado, sem rede) ───────
def _rsa_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _sign(priv, *, aud="mcp:deploy-mcp", **extra) -> str:
    import time

    payload = {"aud": aud, "jti": "jti-1", "exp": int(time.time()) + 300, "tenant_id": "T-1"}
    payload.update(extra)
    return jwt.encode(payload, priv, algorithm="RS256")


def test_verify_inner_token_valid_rs256(monkeypatch):
    priv = _rsa_keypair()
    token = _sign(priv)

    class _Key:
        key = priv.public_key()

    monkeypatch.setattr(
        M.jwt,
        "PyJWKClient",
        lambda url: MagicMock(get_signing_key_from_jwt=lambda t: _Key()),
    )
    claims = M._verify_inner_token(token, _settings())
    assert claims["tenant_id"] == "T-1"
    assert claims["jti"] == "jti-1"


def test_verify_inner_token_wrong_audience_raises(monkeypatch):
    priv = _rsa_keypair()
    token = _sign(priv, aud="mcp:someone-else")

    class _Key:
        key = priv.public_key()

    monkeypatch.setattr(
        M.jwt,
        "PyJWKClient",
        lambda url: MagicMock(get_signing_key_from_jwt=lambda t: _Key()),
    )
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(token, _settings())


def test_verify_inner_token_missing_jti_raises(monkeypatch):
    priv = _rsa_keypair()
    # jwt.encode não coloca jti; o require=["jti"] deve rejeitar.
    import time

    token = jwt.encode(
        {"aud": "mcp:deploy-mcp", "exp": int(time.time()) + 300},
        priv,
        algorithm="RS256",
    )

    class _Key:
        key = priv.public_key()

    monkeypatch.setattr(
        M.jwt,
        "PyJWKClient",
        lambda url: MagicMock(get_signing_key_from_jwt=lambda t: _Key()),
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        M._verify_inner_token(token, _settings())


# ── build_server smoke (fábrica + stdio Server + sidecar) ─────────────────────
def test_build_server_smoke(settings, mock_github, monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: settings)
    server, s, http_app = M.build_server()
    assert server is not None
    assert s.mcp_twin_audience == "mcp:deploy-mcp"  # default via NAMESPACE
    assert http_app.title.startswith("deploy-mcp")


# ─────────────────────────────────────────────────────────────────────────── #
# _dispatch — cobre cada braço chamando a tool subjacente (stubada)            #
# ─────────────────────────────────────────────────────────────────────────── #
_DISPATCH_CASES = {
    "list_repos": ("list_repos", {}),
    "create_branch": ("create_branch", {"repo": "r", "branch": "b"}),
    "list_branches": ("list_branches", {"repo": "r"}),
    "commit_files": ("commit_files", {"repo": "r", "branch": "b", "message": "m", "files": []}),
    "create_pr": ("create_pr", {"repo": "r", "title": "t", "head": "h"}),
    "get_pr": ("get_pr", {"repo": "r", "pr_number": 1}),
    "merge_pr": ("merge_pr", {"repo": "r", "pr_number": 1}),
    "list_prs": ("list_prs", {"repo": "r"}),
    "trigger_workflow": ("trigger_workflow", {"repo": "r", "workflow_id": "w", "ref": "x"}),
    "list_workflow_runs": ("list_workflow_runs", {"repo": "r"}),
    "get_workflow_run": ("get_workflow_run", {"repo": "r", "run_id": 1}),
    "cancel_workflow_run": ("cancel_workflow_run", {"repo": "r", "run_id": 1}),
    "deploy": ("deploy", {"service": "s", "environment": "dev"}),
    "get_deploy_status": ("get_deploy_status", {"service": "s", "environment": "dev"}),
    "scaffold_pipeline": ("scaffold_pipeline", {"repo": "r"}),
    "get_pipeline_templates": ("get_pipeline_templates", {}),
    "setup_repo": ("setup_repo", {"repo": "r", "image_name": "i"}),
    "acr_build": ("acr_build", {"repo_path": "/p", "image_name": "i"}),
    "list_acr_images": ("list_acr_images", {"service_name": "s"}),
    "ensure_all_repos_healthy": ("ensure_all_repos_healthy", {}),
    "get_repos_root": ("get_repos_root", {}),
    "set_repos_root": ("set_repos_root", {"path": "/p"}),
    "list_local_repos": ("list_local_repos", {}),
    "clone_repo": ("clone_repo", {"repo": "r"}),
}


def test_dispatch_cases_cover_all_tools():
    assert set(_DISPATCH_CASES.keys()) == _EXPECTED_TOOLS


@pytest.mark.parametrize("tool_name", sorted(_DISPATCH_CASES.keys()))
def test_dispatch_routes_to_correct_tool(tool_name, settings, gh_client, monkeypatch):
    symbol, args = _DISPATCH_CASES[tool_name]
    sentinel = {"routed": tool_name}
    monkeypatch.setattr(M, symbol, MagicMock(return_value=sentinel))
    result = M._dispatch(tool_name, args, settings, gh_client)
    assert result == sentinel


def test_dispatch_unknown_raises_key_error(settings, gh_client):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {}, settings, gh_client)


# ─────────────────────────────────────────────────────────────────────────── #
# stdio handlers (list_tools / call_tool) do MCP Server                        #
# ─────────────────────────────────────────────────────────────────────────── #
def _handlers(settings, monkeypatch):
    from mcp.types import CallToolRequest, ListToolsRequest

    monkeypatch.setattr(M, "get_settings", lambda: settings)
    server, _s, _http = M.build_server()
    return server.request_handlers[ListToolsRequest], server.request_handlers[CallToolRequest]


async def test_list_tools_handler_returns_all_24(settings, mock_github, monkeypatch):
    from mcp.types import ListToolsRequest

    list_tools, _ = _handlers(settings, monkeypatch)
    res = await list_tools(ListToolsRequest(method="tools/list"))
    tools = res.root.tools
    assert len(tools) == 24
    assert {t.name for t in tools} == _EXPECTED_TOOLS


async def test_call_tool_handler_serializes_payload(settings, mock_github, monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(settings, monkeypatch)
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="get_pipeline_templates", arguments={}),
    )
    res = await call_tool(req)
    assert "templates" in res.root.content[0].text


async def test_call_tool_handler_unknown_tool(settings, mock_github, monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(settings, monkeypatch)
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="does_not_exist", arguments={}),
    )
    res = await call_tool(req)
    assert "unknown_tool" in res.root.content[0].text


async def test_call_tool_handler_internal_error(settings, mock_github, monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(settings, monkeypatch)
    monkeypatch.setattr(M, "_dispatch", MagicMock(side_effect=RuntimeError("kaboom")))
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="get_pipeline_templates", arguments={}),
    )
    res = await call_tool(req)
    text = res.root.content[0].text
    assert "internal_error" in text and "kaboom" in text
