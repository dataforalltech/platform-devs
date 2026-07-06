"""Testes do servidor MCP: lista de tools registradas e dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.server.mcp_server import _TOOL_SCHEMAS, SCOPE_FOR_TOOL, _dispatch

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
    "reload_service",
    # gateway
    "get_gateway_map",
    "update_service_gateway",
    "sync_registry",
    # launch
    "launch_service",
    "stop_service",
    # env
    "read_env_file",
    "set_env_var",
    "sync_service_urls",
    "audit_env_files",
    "redact_env_secrets",
    # infra
    "register_infra",
    "scan_infra",
    "sync_infra_env",
    # brokers
    "kafka_status",
    "redis_status",
    "sync_broker_urls",
    # logs
    "get_service_logs",
    "search_logs",
}


def test_all_tools_registered():
    """Verifica que exatamente as 32 tools esperadas estão em _TOOL_SCHEMAS."""
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED_TOOLS


def test_tool_count():
    assert len(_TOOL_SCHEMAS) == 32


def test_scope_map_covers_every_tool():
    """Least privilege: toda tool tem um escopo mínimo mapeado, sem sobras."""
    assert set(SCOPE_FOR_TOOL.keys()) == set(_TOOL_SCHEMAS.keys())


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


# ── dispatch das tools que cresceram após o teste original ─────────────────── #


def test_update_service_dispatch(store, settings):
    _dispatch("register_service", {"name": "s", "port": 8080}, settings, store)
    result = _dispatch("update_service", {"name": "s", "status": "stopped"}, settings, store)
    assert "status" in result["updated_fields"]


def test_scan_processes_dispatch(store, settings):
    with patch("src.tools.discovery_tool.psutil.net_connections", return_value=[]):
        result = _dispatch("scan_processes", {}, settings, store)
    assert result["total"] == 0


def test_check_health_dispatch_not_found(store, settings):
    result = _dispatch("check_health", {"name": "ghost"}, settings, store)
    assert result["healthy"] is False


def test_check_all_health_dispatch(store, settings):
    result = _dispatch("check_all_health", {}, settings, store)
    assert result["total_checked"] == 0


def test_service_status_dispatch_not_found(store, settings):
    result = _dispatch("service_status", {"name": "ghost"}, settings, store)
    assert result["found"] is False


def test_reload_service_dispatch_not_found(store, settings):
    result = _dispatch("reload_service", {"name": "ghost"}, settings, store)
    assert result["error"] == "not_found"


def test_get_gateway_map_dispatch(store, settings):
    result = _dispatch("get_gateway_map", {}, settings, store)
    assert "gateway" in result


def test_update_service_gateway_dispatch(store, settings):
    _dispatch("register_service", {"name": "s", "port": 8080}, settings, store)
    result = _dispatch("update_service_gateway", {"name": "s", "probe": False}, settings, store)
    assert result["external_url"] == "http://localhost:8080"


def test_sync_registry_dispatch(store, settings):
    with patch("src.tools.gateway_tool.subprocess.run", side_effect=FileNotFoundError):
        result = _dispatch(
            "sync_registry",
            {"include_docker": True, "probe_health": False, "port_ranges": "1-1"},
            settings,
            store,
        )
    assert "total_upserted" in result


def test_launch_service_dispatch_validation(store, settings):
    result = _dispatch(
        "launch_service", {"name": "s", "mode": "uvicorn", "port": 8080}, settings, store
    )
    assert result["error"] == "ValidationError"


def test_stop_service_dispatch_not_found(store, settings):
    result = _dispatch("stop_service", {"name": "ghost"}, settings, store)
    assert result["error"] == "not_found"


def test_read_env_file_dispatch_not_found(store, settings):
    result = _dispatch("read_env_file", {"path": "/no/such.env"}, settings, store)
    assert result["error"] == "FileNotFound"


def test_set_env_var_dispatch(store, settings, tmp_path):
    env = tmp_path / ".env"
    result = _dispatch("set_env_var", {"path": str(env), "key": "A", "value": "1"}, settings, store)
    assert result["action"] == "created"


def test_sync_service_urls_dispatch_not_found(store, settings):
    result = _dispatch("sync_service_urls", {"path": "/no/such.env"}, settings, store)
    assert result["error"] == "FileNotFound"


def test_audit_env_files_dispatch_not_found(store, settings):
    result = _dispatch("audit_env_files", {"directory": "/no/such/dir"}, settings, store)
    assert result["error"] == "DirectoryNotFound"


def test_redact_env_secrets_dispatch(store, settings):
    result = _dispatch("redact_env_secrets", {"paths": ["/no/such.env"]}, settings, store)
    assert result["errors"]


def test_register_infra_dispatch(store, settings):
    result = _dispatch("register_infra", {"name": "redis", "kind": "redis"}, settings, store)
    assert result["action"] == "created"


def test_scan_infra_dispatch(store, settings):
    with patch("src.tools.infra_tool.subprocess.run", side_effect=FileNotFoundError):
        result = _dispatch("scan_infra", {}, settings, store)
    assert result["error"] == "docker not found"


def test_sync_infra_env_dispatch_not_found(store, settings):
    result = _dispatch("sync_infra_env", {"path": "/no/such.env"}, settings, store)
    assert "error" in result


def test_kafka_status_dispatch_not_found(store, settings):
    result = _dispatch("kafka_status", {}, settings, store)
    assert result["ok"] is False


def test_redis_status_dispatch_not_found(store, settings):
    result = _dispatch("redis_status", {}, settings, store)
    assert result["ok"] is False


def test_sync_broker_urls_dispatch_not_found(store, settings):
    result = _dispatch("sync_broker_urls", {"path": "/no/such.env"}, settings, store)
    assert "error" in result


def test_get_service_logs_dispatch_not_found(store, settings):
    result = _dispatch("get_service_logs", {"name": "ghost"}, settings, store)
    assert result["error"] == "not_found"


def test_search_logs_dispatch_not_found(store, settings):
    result = _dispatch("search_logs", {"name": "ghost", "pattern": "x"}, settings, store)
    assert result["error"] == "not_found"
