"""Testes para o mcp_server: montagem do Server, list_tools, dispatch e HTTP.

Exercita build_server() com a camada psycopg2 já trocada por SQLite (via o
monkeypatch do fixture ``store``), evitando qualquer conexão real. O dispatch
interno (o ``match name`` de call_tool, o caminho de exceção e a tool
desconhecida) é exercitado através dos endpoints HTTP, que chamam o handler
interno sem a validação de schema do Server MCP.
"""

import datetime
import json
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from src.server import mcp_server


@pytest.fixture
def built(store):
    """Retorna (server, settings, store, http_app) com o pool fake ativo.

    Depende do fixture ``store`` apenas para reaproveitar o monkeypatch do pool
    psycopg2 -> SQLite antes de build_server() instanciar seu próprio TestStore.
    """
    return mcp_server.build_server()


@pytest.fixture
def client(built):
    _server, _settings, _store, http_app = built
    return TestClient(http_app)


# ── _JSONEncoder ────────────────────────────────────────────────────────────── #


def test_json_encoder_serializes_datetime_and_decimal():
    payload = {
        "when": datetime.datetime(2026, 1, 2, 3, 4, 5),
        "day": datetime.date(2026, 1, 2),
        "amount": Decimal("12.50"),
    }
    out = json.loads(json.dumps(payload, cls=mcp_server._JSONEncoder))
    assert out["when"].startswith("2026-01-02T03:04:05")
    assert out["day"] == "2026-01-02"
    assert out["amount"] == 12.5


def test_json_encoder_raises_on_unknown_type():
    with pytest.raises(TypeError):
        json.dumps({"x": object()}, cls=mcp_server._JSONEncoder)


def test_scope_maps():
    assert mcp_server.SCOPE_FOR_TOOL["create_test_plan"] == "test:write"
    assert mcp_server.SCOPE_FOR_TOOL["get_test_plan"] == "test:read"
    assert set(mcp_server.SCOPES_SUPPORTED) == {"test:read", "test:write"}


# ── list_tools via handler registrado no low-level Server ───────────────────── #


async def test_list_tools_returns_expected_catalog(built):
    server, _settings, _store, _http = built
    tools = await _call_list_tools(server)
    names = {t.name for t in tools}
    assert {"create_test_plan", "add_bug", "double_check", "list_test_plans"} <= names
    for t in tools:
        assert t.inputSchema["type"] == "object"


# ── HTTP: health + tools/list + dispatch completo via tools/call ────────────── #


def test_http_health(client):
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_http_tools_list(client):
    resp = client.get("/mcp/tools/list")
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    assert any(t["name"] == "create_test_plan" for t in tools)


def _call(client, name: str, arguments: dict) -> dict:
    resp = client.post("/mcp/tools/call", json={"params": {"name": name, "arguments": arguments}})
    assert resp.status_code == 200
    text = resp.json()["result"]["content"][0]["text"]
    return json.loads(text)


def test_http_full_dispatch_flow(client):
    # create -> get -> list -> generate -> add_scenario -> record -> checklist
    plan = _call(client, "create_test_plan", {"title": "P", "scope": "S"})
    pid = str(plan["id"])
    assert _call(client, "get_test_plan", {"plan_id": pid})["id"] == plan["id"]
    assert _call(client, "list_test_plans", {})["count"] >= 1

    gen = _call(client, "generate_scenarios", {"plan_id": pid, "category": "rest_api"})
    assert gen["generated_count"] > 0

    sc = _call(
        client,
        "add_scenario",
        {
            "plan_id": pid,
            "name": "S",
            "category": "happy_path",
            "steps": "s",
            "expected_result": "r",
        },
    )
    rec = _call(
        client,
        "record_result",
        {"plan_id": pid, "scenario_id": sc["scenario_id"], "status": "passed"},
    )
    assert rec["status"] == "passed"

    chk = _call(client, "create_checklist", {"title": "C", "checklist_type": "pre_deploy"})
    run = _call(client, "run_checklist", {"checklist_id": chk["checklist_id"]})
    first_item = run["items"][0]["id"]
    checked = _call(
        client,
        "check_item",
        {"run_id": run["run_id"], "item_id": first_item, "status": "passed"},
    )
    assert checked["item_id"] == first_item

    _call(client, "add_bug", {"plan_id": pid, "severity": "low", "title": "T", "description": "D"})
    assert "verdict" in _call(client, "double_check", {"plan_id": pid})
    assert "grade" in _call(client, "get_validation_status", {"plan_id": pid})


def test_http_unknown_tool(client):
    data = _call(client, "does_not_exist", {})
    assert data["error"] == "UnknownTool"


def test_http_dispatch_exception_is_caught(client):
    # kwargs inesperados chegam ao tool via **arguments -> TypeError, capturado
    # pelo except do call_tool e serializado como erro (não propaga 500).
    data = _call(client, "create_test_plan", {"argumento_invalido": 1})
    assert "error" in data


# ── Helper para acessar o handler list_tools do low-level Server ────────────── #


def _find_handler(server, needle: str):
    for req_type, fn in server.request_handlers.items():
        if needle in req_type.__name__.lower():
            return fn
    raise AssertionError(f"handler {needle} não encontrado")


async def _call_list_tools(server):
    from mcp import types

    fn = _find_handler(server, "listtools")
    result = await fn(types.ListToolsRequest(method="tools/list"))
    return result.root.tools
