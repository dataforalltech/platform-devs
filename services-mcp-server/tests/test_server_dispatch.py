"""Testes do servidor MCP: lista de tools registradas e dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.server.mcp_server import _TOOL_SCHEMAS, _dispatch

_EXPECTED_TOOLS = {
    # registry
    "register_service",
    "get_service",
    "list_services",
    "update_service",
    "unregister_service",
    # portmap
    "get_port_map",
    "find_by_port",
    # discovery
    "scan_docker",
    "scan_processes",
    "check_health",
    "check_all_health",
    # composite
    "service_status",
    "list_environments",
}


def test_all_tools_registered():
    """Verifica que exatamente as 13 tools esperadas estão em _TOOL_SCHEMAS."""
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 13


def test_each_tool_has_description_and_schema():
    for name, meta in _TOOL_SCHEMAS.items():
        assert "description" in meta, f"{name}: falta 'description'"
        assert "schema" in meta, f"{name}: falta 'schema'"
        assert meta["description"].strip(), f"{name}: description vazia"
        schema = meta["schema"]
        assert schema.get("type") == "object", f"{name}: schema.type deve ser 'object'"
        assert "properties" in schema, f"{name}: schema.properties faltando"


def test_required_fields_are_in_properties():
    """required[] deve referenciar apenas campos definidos em properties."""
    for name, meta in _TOOL_SCHEMAS.items():
        schema = meta["schema"]
        props = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        missing = required - props
        assert not missing, f"{name}: required {missing} não estão em properties"


def test_unknown_tool_raises_key_error(store, settings):
    with pytest.raises(KeyError):
        _dispatch("non_existent_tool_xyz", {}, settings, store)


def test_get_port_map_dispatch(store, settings):
    """get_port_map não requer args — deve retornar dict com port_map."""
    result = _dispatch("get_port_map", {}, settings, store)
    assert "port_map" in result
    assert result["total"] == 0


def test_list_environments_dispatch(store, settings):
    """list_environments não requer args — deve retornar dict com environments."""
    result = _dispatch("list_environments", {}, settings, store)
    assert "environments" in result
    assert result["total_services"] == 0


def test_register_service_dispatch(store, settings):
    result = _dispatch(
        "register_service",
        {"name": "test-svc", "port": 8080},
        settings,
        store,
    )
    assert result["action"] == "created"
    assert result["name"] == "test-svc"


def test_get_service_dispatch(store, settings):
    _dispatch("register_service", {"name": "test-svc", "port": 8080}, settings, store)
    result = _dispatch("get_service", {"name": "test-svc"}, settings, store)
    assert result["found"] is True


def test_unregister_service_dispatch(store, settings):
    _dispatch("register_service", {"name": "test-svc", "port": 8080}, settings, store)
    result = _dispatch("unregister_service", {"name": "test-svc"}, settings, store)
    assert result["deleted"] is True


def test_find_by_port_dispatch(store, settings):
    result = _dispatch("find_by_port", {"port": 8080}, settings, store)
    assert result["found"] is False
    assert result["port"] == 8080


def test_scan_docker_dispatch_docker_not_installed(store, settings):
    with patch("src.tools.discovery_tool.subprocess.run", side_effect=FileNotFoundError):
        result = _dispatch("scan_docker", {}, settings, store)
    assert "docker_error" in result
    assert result["docker_error"] is not None
