"""Sidecar mcp_http + PEP inner-token (RS256 REAL) — §16 / Test Doubles Policy.

RS256 é real: chave gerada, token assinado, verificador real (o PyJWKClient serve a
chave pública local — sem bypass, sem HS*). Os caminhos de catálogo/PEP que retornam
antes do DB são herméticos; o dispatch/run_tool com estado roda contra MySQL real.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config.settings import ServicesSettings
from src.server import mcp_server as M
from src.tools import broker_tool, discovery_tool, gateway_tool, infra_tool

from .conftest import (
    TENANT_A,
    _test_settings,
    mint_token,
    patch_jwks,
    requires_mysql,
)

_EXPECTED_TOOLS = {
    "register_service",
    "get_service",
    "list_services",
    "update_service",
    "unregister_service",
    "get_port_map",
    "find_by_port",
    "scan_docker",
    "scan_processes",
    "check_health",
    "check_all_health",
    "service_status",
    "list_environments",
    "reload_service",
    "get_gateway_map",
    "update_service_gateway",
    "sync_registry",
    "launch_service",
    "stop_service",
    "read_env_file",
    "set_env_var",
    "sync_service_urls",
    "audit_env_files",
    "redact_env_secrets",
    "register_infra",
    "scan_infra",
    "sync_infra_env",
    "kafka_status",
    "redis_status",
    "sync_broker_urls",
    "get_service_logs",
    "search_logs",
}


def _settings(**over) -> ServicesSettings:
    return ServicesSettings(
        MCP_TWIN_AUDIENCE="mcp:services-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        **over,
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(M._build_http_app(_settings()))


# ── Schemas / catálogo (sem DB) ───────────────────────────────────────────────
def test_tool_count():
    assert len(M._TOOL_SCHEMAS) == 32
    assert set(M._TOOL_SCHEMAS) == _EXPECTED_TOOLS
    assert set(M.SCOPE_FOR_TOOL) == _EXPECTED_TOOLS


def test_required_fields_are_subset_of_properties():
    for name, meta in M._TOOL_SCHEMAS.items():
        props = set(meta["schema"].get("properties", {}).keys())
        required = set(meta["schema"].get("required", []))
        assert required <= props, f"{name}: required fora de properties"


def test_health(client: TestClient):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "services-mcp", "tools": 31}


def test_tools_list_has_policy_fields(client: TestClient):
    tools = client.get("/mcp/tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == _EXPECTED_TOOLS - M._EXCLUDE_TOOLS
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        for field in ("capability", "required_scope", "resource_type", "data_domain"):
            assert t[field], f"{t['name']} sem {field}"
        assert t["required_scope"].count(":") == 2
        assert t["capability"] == f"services-mcp.{t['name']}"
        assert t["required_scope"].startswith("services-mcp:")
    by_name = {t["name"]: t for t in tools}
    # mutações usam verbo :write; consultas :read
    assert by_name["register_service"]["required_scope"].endswith(":write")
    assert by_name["reload_service"]["required_scope"].endswith(":write")
    assert by_name["set_env_var"]["required_scope"].endswith(":write")
    assert by_name["get_service"]["required_scope"].endswith(":read")
    assert by_name["list_services"]["required_scope"].endswith(":read")
    # data_domain especializado
    assert "read_env_file" not in by_name
    assert by_name["get_service_logs"]["data_domain"] == "observability"
    assert by_name["get_service"]["data_domain"] == "infrastructure"


# ── /mcp/tools/call — PEP (RS256 real), caminhos que retornam antes do DB ──────
def test_call_missing_twin_token(client: TestClient):
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_service", "arguments": {"name": "x"}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_twin_token"


def test_call_invalid_audience_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, aud="mcp:outro-servico")  # audiência errada → verificador real rejeita
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_service", "arguments": {"name": "x"}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_jti_rejected(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, include_jti=False)  # sem jti → require falha
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_service", "arguments": {"name": "x"}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_twin_token"


def test_call_token_without_tenant(client: TestClient, monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id=None)  # verifica OK mas sem tenant nas claims
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_service", "arguments": {"name": "x"}, "_meta": {"twin_token": tok}}},
    )
    assert r.status_code == 401 and r.json()["error"] == "missing_tenant_scope"


def test_call_excluded_tool(client: TestClient, monkeypatch):
    monkeypatch.setattr(M, "_EXCLUDE_TOOLS", frozenset({"get_service"}))
    r = client.post(
        "/mcp/tools/call",
        json={"params": {"name": "get_service", "arguments": {"name": "x"}}},
    )
    assert r.status_code == 403 and r.json()["error"] == "tool_excluded"


# ── _verify_inner_token (RS256 real) ──────────────────────────────────────────
def test_verify_inner_token_unconfigured():
    s = ServicesSettings(MCP_TWIN_AUDIENCE="", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(PermissionError):
        M._verify_inner_token("tok", s)


def test_verify_inner_token_real_rs256(monkeypatch, rsa_key):
    patch_jwks(monkeypatch, rsa_key)
    claims = M._verify_inner_token(mint_token(rsa_key, tenant_id="T-9"), _settings())
    assert claims["tenant_id"] == "T-9"
    with pytest.raises(jwt.InvalidAudienceError):
        M._verify_inner_token(mint_token(rsa_key, aud="mcp:x"), _settings())


# ── build_server: fábrica + sidecar (stdio gateway-only) ──────────────────────
def test_build_server_smoke(monkeypatch):
    monkeypatch.setattr(M, "get_settings", lambda: _settings())
    server, settings, http_app = M.build_server()
    assert server is not None
    assert settings.mcp_twin_audience == "mcp:services-mcp"
    assert http_app.title.startswith("services-mcp")
    assert TestClient(http_app).get("/v1/health").json()["service"] == "services-mcp"


# ── Execução com estado (MySQL real) ──────────────────────────────────────────
@pytest.fixture()
def _patched_externals(monkeypatch):
    """Neutraliza docker/psutil/httpx/socket para o roteamento do dispatch não tocar rede."""

    def _no_docker(*_a, **_k):
        raise FileNotFoundError

    for mod in (discovery_tool, gateway_tool, infra_tool):
        monkeypatch.setattr(mod.subprocess, "run", _no_docker)

    import psutil

    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": [])

    class _Resp:
        status_code = 200

    class _Client:
        def __call__(self, *_a, **_k):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_e):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(discovery_tool.httpx, "Client", _Client())

    def _no_socket(*_a, **_k):
        raise OSError("refused")

    monkeypatch.setattr(broker_tool.socket, "create_connection", _no_socket)

    # sync_registry cai no default "8000-8100" quando port_ranges="" (falsy): stub o scan
    # de portas p/ não fazer HTTP real a localhost (determinístico + rápido).
    async def _no_port_scan(store, ranges_str, *, probe=True, timeout=1.5):
        return {"scanned": 0, "found": 0, "services": []}

    monkeypatch.setattr(gateway_tool, "_scan_port_ranges", _no_port_scan)


@pytest.mark.integration
@requires_mysql
async def test_dispatch_routes_all_tools(store_a, tmp_path, _patched_externals):
    s = _test_settings()

    async def d(name, args):
        return await M._dispatch(name, args, store_a, s)

    # Registry / PortMap
    assert (await d("register_service", {"name": "svc", "port": 8080}))["action"] == "created"
    assert (await d("get_service", {"name": "svc"}))["found"] is True
    assert (await d("list_services", {}))["total"] >= 1
    assert (await d("update_service", {"name": "svc", "status": "running"}))["name"] == "svc"
    assert "port_map" in await d("get_port_map", {})
    assert (await d("find_by_port", {"port": 8080}))["found"] is True
    # Discovery
    assert (await d("scan_docker", {}))["docker_error"] == "docker not found"
    assert (await d("scan_processes", {}))["total"] == 0
    assert (await d("check_health", {"name": "ghost"}))["error"] == "not_found"
    assert "total_checked" in await d("check_all_health", {})
    # Composite
    assert (await d("service_status", {"name": "ghost"}))["found"] is False
    assert "environments" in await d("list_environments", {})
    assert (await d("reload_service", {"name": "ghost"}))["error"] == "not_found"
    # Gateway
    assert "gateway" in await d("get_gateway_map", {})
    assert (await d("update_service_gateway", {"name": "ghost"}))["error"] == "not_found"
    assert (await d("sync_registry", {"port_ranges": "", "probe_health": False}))["total_upserted"] == 0
    # Launch
    assert (await d("launch_service", {"name": "x", "mode": "uvicorn", "port": 9999}))[
        "error"
    ] == "ValidationError"
    assert (await d("stop_service", {"name": "ghost"}))["error"] == "not_found"
    # Env
    assert (await d("read_env_file", {"path": str(tmp_path / "none.env")}))["error"] == "FileNotFound"
    assert (await d("set_env_var", {"path": str(tmp_path / "w.env"), "key": "K", "value": "v"}))[
        "action"
    ] == "created"
    assert (await d("sync_service_urls", {"path": str(tmp_path / "none.env")}))["error"] == "FileNotFound"
    assert (await d("audit_env_files", {"directory": str(tmp_path / "nope")}))["error"] == "DirectoryNotFound"
    assert "errors" in await d("redact_env_secrets", {"paths": [str(tmp_path / "none.env")]})
    # Infra
    assert (await d("register_infra", {"name": "mysqldb", "kind": "mysql"}))["action"] == "created"
    assert (await d("scan_infra", {}))["error"] == "docker not found"
    assert "error" in await d("sync_infra_env", {"path": str(tmp_path / "none.env")})
    # Brokers
    assert (await d("kafka_status", {"bootstrap_servers": "localhost:9092"}))["ok"] is False
    assert (await d("redis_status", {"url": "redis://localhost:6379/0"}))["ok"] is False
    assert "error" in await d("sync_broker_urls", {"path": str(tmp_path / "none.env")})
    # Logs
    assert (await d("get_service_logs", {"name": "ghost"}))["error"] == "not_found"
    assert (await d("search_logs", {"name": "ghost", "pattern": "x"}))["error"] == "not_found"
    # unknown → KeyError
    with pytest.raises(KeyError):
        await d("does_not_exist", {})


@pytest.mark.integration
@requires_mysql
async def test_run_tool_credential_zero_end_to_end(seed_platforms):
    """Caminho REAL: _run_tool -> _ensure_tenant_schema -> for_tenant (get_platform ->
    PLATFORMS) -> ServiceStore -> _dispatch, tudo em MySQL real."""
    M._SCHEMA_READY.discard(TENANT_A)
    settings = _test_settings()  # com ADMIN_DB_*/DB_* reais (resolve o tenant via PLATFORMS)
    created = await M._run_tool("register_service", {"name": "e2e", "port": 8080}, settings, TENANT_A)
    assert created["action"] == "created"
    # segunda chamada: _SCHEMA_READY já contém o tenant (early-return do bootstrap)
    got = await M._run_tool("get_service", {"name": "e2e"}, settings, TENANT_A)
    assert got["found"] is True
    with pytest.raises(KeyError):
        await M._run_tool("nope", {}, settings, TENANT_A)


# ── /mcp/tools/call — caminhos após o PEP (run_tool mockado; PEP RS256 real) ──
# O tenant vem dos claims verificados; `_run_tool` (que tocaria o banco do tenant) é
# substituído para exercitar a serialização/erros do endpoint de forma hermética.
def _authed_post(client: TestClient, monkeypatch, rsa_key, name: str):
    patch_jwks(monkeypatch, rsa_key)
    tok = mint_token(rsa_key, tenant_id="T-1")
    return client.post(
        "/mcp/tools/call",
        json={"params": {"name": name, "arguments": {}, "_meta": {"twin_token": tok}}},
    )


def test_http_call_success(client: TestClient, monkeypatch, rsa_key):
    async def _fake_run(name, arguments, settings, tenant_id):
        assert tenant_id == "T-1"  # tenant veio dos claims verificados
        return {"ok": True, "tool": name}

    monkeypatch.setattr(M, "_run_tool", _fake_run)
    r = _authed_post(client, monkeypatch, rsa_key, "get_service")
    assert r.status_code == 200
    content = r.json()["result"]["content"]
    assert content[0]["type"] == "text"
    assert "ok" in content[0]["text"]


def test_http_call_unknown_tool(client: TestClient, monkeypatch, rsa_key):
    async def _fake_run(*_a, **_k):
        raise KeyError("nope")

    monkeypatch.setattr(M, "_run_tool", _fake_run)
    r = _authed_post(client, monkeypatch, rsa_key, "does_not_exist")
    assert r.status_code == 404 and r.json()["error"] == "unknown_tool"


def test_http_call_internal_error(client: TestClient, monkeypatch, rsa_key):
    async def _fake_run(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(M, "_run_tool", _fake_run)
    r = _authed_post(client, monkeypatch, rsa_key, "get_service")
    assert r.status_code == 200
    payload = r.json()["result"]["content"][0]["text"]
    assert "internal_error" in payload and "kaboom" in payload
