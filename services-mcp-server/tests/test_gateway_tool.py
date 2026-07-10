"""Testes das tools de gateway (map/update/sync_registry).

Herméticos: _is_docker, subprocess e httpx (via _probe_url/_identify_service) mockados.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tools import gateway_tool
from src.tools.gateway_tool import (
    _derive_external_url,
    _derive_internal_url,
    _parse_container_port,
    _parse_first_host_port,
    get_gateway_map,
    sync_registry,
    update_service_gateway,
)

from .conftest import make_service

# ── helpers puros ─────────────────────────────────────────────────────────── #


def test_derive_internal_url():
    assert _derive_internal_url("svc", 8080, "cont") == "http://cont:8080"
    assert _derive_internal_url("svc", None) is None


def test_derive_external_url_normalizes_bind_all():
    assert _derive_external_url("0.0.0.0", 8080) == "http://localhost:8080"


def test_parse_ports():
    assert _parse_first_host_port("0.0.0.0:8080->80/tcp") == 8080
    assert _parse_container_port("0.0.0.0:8080->80/tcp") == 80


# ── get_gateway_map ───────────────────────────────────────────────────────── #


def test_get_gateway_map_local_context(store):
    make_service(store, name="svc-a", port=8080)
    with patch.object(gateway_tool, "_is_docker", return_value=False):
        result = get_gateway_map(store)
    assert result["context"] == "local"
    assert result["total"] == 1
    entry = result["gateway"]["svc-a"]
    assert entry["active_url"] == entry["external_url"]


def test_get_gateway_map_docker_context(store):
    make_service(store, name="svc-a", port=8080)
    with patch.object(gateway_tool, "_is_docker", return_value=True):
        result = get_gateway_map(store)
    assert result["context"] == "docker"
    entry = result["gateway"]["svc-a"]
    assert entry["active_url"] == entry["internal_url"]


# ── update_service_gateway ────────────────────────────────────────────────── #


def test_update_gateway_not_found(store):
    result = update_service_gateway(store, name="ghost")
    assert result["error"] == "not_found"


def test_update_gateway_no_probe(store):
    make_service(store, name="svc-a", port=8080)
    result = update_service_gateway(store, name="svc-a", probe=False)
    assert result["external_url"] == "http://localhost:8080"
    assert result["internal_url"] == "http://svc-a:8080"


def test_update_gateway_probe_running(store):
    make_service(store, name="svc-a", port=8080)
    with (
        patch.object(gateway_tool, "_is_docker", return_value=False),
        patch.object(gateway_tool, "_probe_url", return_value=True),
    ):
        result = update_service_gateway(store, name="svc-a", probe=True)
    assert result["status"] == "running"


def test_update_gateway_probe_stopped(store):
    make_service(store, name="svc-a", port=8080)
    with (
        patch.object(gateway_tool, "_is_docker", return_value=False),
        patch.object(gateway_tool, "_probe_url", return_value=False),
    ):
        result = update_service_gateway(store, name="svc-a", probe=True)
    assert result["status"] == "stopped"


# ── sync_registry ─────────────────────────────────────────────────────────── #


def _docker_ps(*lines: str) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = "\n".join(lines) + "\n"
    m.stderr = ""
    return m


def test_sync_registry_docker_scan(store):
    line = '{"ID":"a1b2c3d4","Names":"api","Image":"api:1","Ports":"0.0.0.0:8080->80/tcp"}'
    with (
        patch.object(gateway_tool, "_is_docker", return_value=False),
        patch("src.tools.gateway_tool.subprocess.run", return_value=_docker_ps(line)),
        # sem port scan / probes reais
        patch.object(gateway_tool, "_probe_url", return_value=False),
    ):
        result = sync_registry(store, include_docker=True, probe_health=True, port_ranges="8000-8000")
    assert result["docker_scan"]["upserted"] == 1
    assert store.get("api") is not None
    assert result["total_upserted"] >= 1


def test_sync_registry_docker_not_found(store):
    with (
        patch.object(gateway_tool, "_is_docker", return_value=False),
        patch("src.tools.gateway_tool.subprocess.run", side_effect=FileNotFoundError),
        patch.object(gateway_tool, "_probe_url", return_value=False),
    ):
        result = sync_registry(store, include_docker=True, probe_health=True, port_ranges="8000-8000")
    assert result["docker_scan"]["error"] == "docker not found"


def test_sync_registry_port_scan_identifies_service(store):
    with (
        patch.object(gateway_tool, "_is_docker", return_value=False),
        patch.object(gateway_tool, "_probe_url", return_value=True),
        patch.object(gateway_tool, "_identify_service", return_value="found-svc"),
    ):
        result = sync_registry(
            store,
            include_docker=False,
            probe_health=True,
            port_ranges="8080-8080",
        )
    assert result["port_scan"]["found"] == 1
    assert store.get("found-svc") is not None


def test_sync_registry_name_scan(store):
    make_service(store, name="known", port=9000)
    with (
        patch.object(gateway_tool, "_is_docker", return_value=False),
        patch.object(gateway_tool, "_probe_url", return_value=True),
    ):
        result = sync_registry(
            store,
            include_docker=False,
            probe_health=True,
            port_ranges="1-1",
            service_names=["known"],
        )
    assert result["name_scan"]["found"] == 1
