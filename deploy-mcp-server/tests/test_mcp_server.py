"""Sidecar mcp_http + PEP inner-token (RS256 REAL) + ledger tenant-scoped — §16.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). O caminho de execução com estado (persiste
o ledger / lê o ledger) roda contra MySQL real via `_run_tool`/`DeployStore`. As tools
de ação FAZEM a ação (FakeGitHubClient, duplo do backend externo — FID-01) e DEPOIS
persistem o ledger no banco do tenant (FID-02).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import DeploySettings
from src.server import mcp_server as M

from .conftest import (
    TENANT_A,
    FakeGitHubClient,
    _test_settings,
    mint_token,
    patch_jwks,
    requires_mysql,
)

_LEDGER_TOOLS = {
    "list_deployments",
    "get_deployment",
    "list_deploy_events",
    "list_pr_history",
    "list_workflow_history",
    "list_registered_repos",
}

_ACTION_COMPUTE_TOOLS = {
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

_EXPECTED_TOOLS = _ACTION_COMPUTE_TOOLS | _LEDGER_TOOLS


def _settings(**over) -> DeploySettings:
    return DeploySettings(
        github_token="test_token_ghp_xxx",
        github_org="test-org",
        MCP_TWIN_AUDIENCE="mcp:deploy-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/.well-known/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    s = _settings()
    # Backend externo mockado (FakeGitHubClient) — nenhuma chamada real à API.
    return TestClient(M._build_http_app(s, FakeGitHubClient(s)))


@pytest.fixture()
def gh_client() -> MagicMock:
    return MagicMock()


# ══════════════════════════════════════════════════════════════════════════════
# Schemas / catálogo (sem DB)
# ══════════════════════════════════════════════════════════════════════════════
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 30
    assert set(M._TOOL_SCHEMAS) == _EXPECTED_TOOLS


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "deploy-mcp", "tools": 30}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS
    by_name = {t["name"]: t for t in tools}
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["required_scope"].startswith("deploy-mcp:")
        assert t["capability"] == f"deploy-mcp.{t['name']}"
    # ledger (consulta) usa verbo :read; mutadores usam :write
    for name in _LEDGER_TOOLS:
        assert by_name[name]["required_scope"].endswith(":read")
    assert by_name["deploy"]["required_scope"].endswith(":write")
    assert by_name["merge_pr"]["required_scope"].endswith(":write")


# ══════════════════════════════════════════════════════════════════════════════
# /mcp/tools/call — PEP (RS256 real), caminhos que retornam ANTES do DB
# ══════════════════════════════════════════════════════════════════════════════
def test_call_missing_twin_token(client: TestClient):
    r = client.post("/mcp/tools/call", json={"params": {"name": "list_repos", "arguments": {}}})
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_expired_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, exp_delta=-10)  # já expirado → rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "list_repos", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"list_repos"}))
    r = client.post("/mcp/tools/call", json={"params": {"name": "list_repos", "arguments": {}}})
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


def test_call_valid_token_compute_tool_no_db(client: TestClient, monkeypatch, rsa_key):
    """Happy path SEM DB: tool compute (get_pipeline_templates) roda via _run_tool sem
    abrir pool — exercita o handler async + verificação RS256 real + tenant dos claims."""
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id="T-42")
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_pipeline_templates", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 200
    import json

    text = r.json()["result"]["content"][0]["text"]
    assert "templates" in json.loads(text)


def test_call_unknown_tool_404(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id="T-1")
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "does_not_exist", "arguments": {}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 404 and r.json()["error"] == "unknown_tool"


# ══════════════════════════════════════════════════════════════════════════════
# _verify_inner_token (RS256 real)
# ══════════════════════════════════════════════════════════════════════════════
def test_verify_inner_token_unconfigured():
    s = DeploySettings(github_token="t", MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


def test_verify_inner_token_missing_jti(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    with pytest.raises(jwt.MissingRequiredClaimError):
        M._verify_inner_token(mint_token(rsa_key, include_jti=False), _settings())


# ══════════════════════════════════════════════════════════════════════════════
# build_server smoke + stdio (gateway-only, fail-closed)
# ══════════════════════════════════════════════════════════════════════════════
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert settings.mcp_twin_audience == "mcp:deploy-mcp"
    assert http_app.title.startswith("deploy-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "deploy-mcp"


def _handlers(monkeypatch):
    from mcp.types import CallToolRequest, ListToolsRequest

    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, _s, _http = M.build_server()
    return server.request_handlers[ListToolsRequest], server.request_handlers[CallToolRequest]


async def test_list_tools_handler_returns_all_30(monkeypatch):
    from mcp.types import ListToolsRequest

    list_tools, _ = _handlers(monkeypatch)
    res = await list_tools(ListToolsRequest(method="tools/list"))
    tools = res.root.tools
    assert len(tools) == 30
    assert {t.name for t in tools} == _EXPECTED_TOOLS


async def test_call_tool_handler_is_fail_closed(monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(monkeypatch)
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="list_repos", arguments={}),
    )
    res = await call_tool(req)
    assert "tenant_context_required" in res.root.content[0].text


async def test_call_tool_handler_unknown_tool(monkeypatch):
    from mcp.types import CallToolRequest, CallToolRequestParams

    _, call_tool = _handlers(monkeypatch)
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="does_not_exist", arguments={}),
    )
    res = await call_tool(req)
    assert "unknown_tool" in res.root.content[0].text


# ══════════════════════════════════════════════════════════════════════════════
# _dispatch — roteia cada uma das 24 tools compute/ação (stubada, sem DB)
# ══════════════════════════════════════════════════════════════════════════════
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


def test_dispatch_cases_cover_all_action_tools():
    assert set(_DISPATCH_CASES.keys()) == _ACTION_COMPUTE_TOOLS


@pytest.mark.parametrize("tool_name", sorted(_DISPATCH_CASES.keys()))
def test_dispatch_routes_to_correct_tool(tool_name, settings, gh_client, monkeypatch):
    symbol, args = _DISPATCH_CASES[tool_name]
    sentinel = {"routed": tool_name}
    monkeypatch.setattr(M, symbol, MagicMock(return_value=sentinel))
    assert M._dispatch(tool_name, args, settings, gh_client) == sentinel


def test_dispatch_unknown_raises_key_error(settings, gh_client):
    with pytest.raises(KeyError):
        M._dispatch("does_not_exist", {}, settings, gh_client)


async def test_dispatch_ledger_unknown_raises_key_error():
    # tool desconhecida no dispatcher do ledger (não toca o store → sem DB).
    with pytest.raises(KeyError):
        await M._dispatch_ledger("nope", {}, store=None)  # type: ignore[arg-type]


def test_is_ok_helper():
    assert M._is_ok({"ok": True}) is True
    assert M._is_ok({"error": "x"}) is False
    assert M._is_ok("not a dict") is False


# ══════════════════════════════════════════════════════════════════════════════
# Execução com estado (MySQL real): _run_tool faz a ação e persiste o ledger,
# e as query tools leem o histórico — tudo credencial-zero (PLATFORMS).
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.integration
@requires_mysql
async def test_run_tool_persists_and_reads_ledger(seed_platforms, monkeypatch):
    M._SCHEMA_READY.discard(TENANT_A)
    s = _test_settings()
    c = FakeGitHubClient(s)

    async def run(name, args):
        return await M._run_tool(name, args, s, c, TENANT_A)

    # deploy → DeploymentRow (append-only)
    dep = await run("deploy", {"service": "svc", "environment": "dev"})
    assert dep["dispatched"] is True
    depl = await run("list_deployments", {})
    assert depl["total"] == 1
    assert depl["deployments"][0]["service"] == "svc"
    assert depl["deployments"][0]["environment"] == "dev"
    assert depl["deployments"][0]["detail"]["workflow"] == "cd-dev.yml"  # JSON round-trip
    got = await run("get_deployment", {"id": depl["deployments"][0]["id"]})
    assert got["workflow"] == "cd-dev.yml"

    # create_pr → PR upsert; merge_pr → state='merged' (mesma (repo,number), sem dup)
    await run("create_pr", {"repo": "svc", "title": "feat: x", "head": "feature/x"})
    await run("merge_pr", {"repo": "svc", "pr_number": 7})
    prs = await run("list_pr_history", {})
    assert prs["total"] == 1  # upsert, não duplica
    assert prs["pull_requests"][0]["state"] == "merged"
    assert prs["pull_requests"][0]["title"] == "feat: x"  # preservado (merge semantics)

    # get_pr → PR upsert refresh (mesmo número, ainda 1 linha)
    await run("get_pr", {"repo": "svc", "pr_number": 7})
    assert (await run("list_pr_history", {"repo": "svc"}))["total"] == 1

    # trigger_workflow → DeployEvent(kind=trigger_workflow) (dispatch não traz run_id)
    await run("trigger_workflow", {"repo": "svc", "workflow_id": "ci.yml", "ref": "develop"})
    assert (await run("list_deploy_events", {"kind": "trigger_workflow"}))["total"] == 1

    # get_workflow_run → WorkflowRun upsert (run_id do GitHub — VARCHAR)
    await run("get_workflow_run", {"repo": "svc", "run_id": 10000000000})
    wf = await run("list_workflow_history", {})
    assert wf["total"] == 1
    assert wf["workflow_runs"][0]["run_id"] == "10000000000"
    assert wf["workflow_runs"][0]["conclusion"] == "success"

    # cancel_workflow_run → DeployEvent(kind=cancel_run)
    await run("cancel_workflow_run", {"repo": "svc", "run_id": 999})
    assert (await run("list_deploy_events", {"kind": "cancel_run"}))["total"] == 1

    # commit_files → DeployEvent(kind=commit)
    await run(
        "commit_files",
        {"repo": "svc", "branch": "develop", "message": "m", "files": [{"path": "a", "content": "c"}]},
    )
    assert (await run("list_deploy_events", {"kind": "commit"}))["total"] == 1

    # scaffold_pipeline → DeployEvent(kind=scaffold_pipeline) (usa client.commit_files)
    await run("scaffold_pipeline", {"repo": "svc", "templates": ["ci"]})
    assert (await run("list_deploy_events", {"kind": "scaffold_pipeline"}))["total"] == 1

    # setup_repo → Repo upsert
    await run("setup_repo", {"repo": "svc", "image_name": "svc"})
    repos = await run("list_registered_repos", {})
    assert repos["total"] == 1 and repos["repos"][0]["repo"] == "svc"

    # clone_repo / acr_build usam subprocess → stub direto do símbolo p/ persistir evento
    monkeypatch.setattr(
        M, "clone_repo", lambda *a, **k: {"repo": "org/svc", "path": "/x", "action": "cloned"}
    )
    monkeypatch.setattr(M, "acr_build", lambda *a, **k: {"success": True, "image": "img:v1", "tag": "v1"})
    await run("clone_repo", {"repo": "svc"})
    await run("acr_build", {"repo_path": "/x", "image_name": "svc"})
    assert (await run("list_deploy_events", {"kind": "clone"}))["total"] == 1
    assert (await run("list_deploy_events", {"kind": "acr_build"}))["total"] == 1

    # create_branch → BranchRow (sem query tool → confirma via _run_tool não-erro + count)
    br = await run("create_branch", {"repo": "svc", "branch": "feature/y"})
    assert br["branch"] == "feature/y"

    # tool desconhecida → KeyError (propaga p/ o handler HTTP virar 404)
    with pytest.raises(KeyError):
        await run("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_run_tool_skips_ledger_on_action_error(seed_platforms):
    """Se a ação retorna erro (ex.: environment inválido), o ledger NÃO persiste."""
    M._SCHEMA_READY.discard(TENANT_A)
    s = _test_settings()
    c = FakeGitHubClient(s)
    bad = await M._run_tool("deploy", {"service": "svc", "environment": "nope"}, s, c, TENANT_A)
    assert bad["error"] == "ValidationError"
    listed = await M._run_tool("list_deployments", {}, s, c, TENANT_A)
    assert listed["total"] == 0  # nada persistido
