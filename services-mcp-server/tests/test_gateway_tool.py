"""Gateway: MAPPING_GATEWAY, update_service_gateway e sync_registry.

Banco real (FID-02); docker/httpx probes são o único duplo.
"""

from __future__ import annotations

import json

import pytest

from src.tools import gateway_tool
from src.tools.gateway_tool import (
    _derive_external_url,
    _derive_internal_url,
    _parse_container_port,
    _parse_first_host_port,
    _scan_by_names,
    _scan_port_ranges,
    get_gateway_map,
    sync_registry,
    update_service_gateway,
)
from src.tools.registry_tool import register_service

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


async def _no_port_scan(store, ranges_str, *, probe=True, timeout=1.5):
    """Stub do scan de portas: evita HTTP real a localhost:8000-8100 (determinístico)."""
    return {"scanned": 0, "found": 0, "services": []}


# ── helpers puros ─────────────────────────────────────────────────────────────
def test_derive_urls():
    assert _derive_internal_url("svc", 8080) == "http://svc:8080"
    assert _derive_internal_url("svc", 8080, "/ctr") == "http://ctr:8080"
    assert _derive_internal_url("svc", None) is None
    assert _derive_external_url("0.0.0.0", 8080) == "http://localhost:8080"
    assert _derive_external_url("myhost", 8080) == "http://myhost:8080"
    assert _derive_external_url("host", None) is None


def test_parse_ports():
    assert _parse_first_host_port("0.0.0.0:8080->80/tcp") == 8080
    assert _parse_first_host_port("") is None
    assert _parse_container_port("0.0.0.0:8080->80/tcp") == 80
    assert _parse_container_port("noports") is None


# ── get_gateway_map ───────────────────────────────────────────────────────────
async def test_get_gateway_map_local(store_a):
    await register_service(store_a, name="svc", port=8080, host="localhost")
    result = await get_gateway_map(store_a)
    assert result["context"] == "local"
    assert result["total"] == 1
    entry = result["gateway"]["svc"]
    assert entry["external_url"] == "http://localhost:8080"
    assert entry["internal_url"] == "http://svc:8080"
    assert entry["active_url"] == entry["external_url"]


async def test_get_gateway_map_docker_context(store_a, monkeypatch):
    monkeypatch.setattr(gateway_tool, "_is_docker", lambda: True)
    await register_service(store_a, name="svc", port=8080)
    result = await get_gateway_map(store_a)
    assert result["context"] == "docker"
    assert result["gateway"]["svc"]["active_url"] == "http://svc:8080"


# ── update_service_gateway ────────────────────────────────────────────────────
async def test_update_gateway_not_found(store_a):
    assert (await update_service_gateway(store_a, name="ghost"))["error"] == "not_found"


async def test_update_gateway_derives_without_probe(store_a):
    await register_service(store_a, name="svc", port=8080, host="localhost")
    result = await update_service_gateway(store_a, name="svc", probe=False)
    assert result["internal_url"] == "http://svc:8080"
    assert result["external_url"] == "http://localhost:8080"
    assert result["probe"] == {}
    row = await store_a.get("svc")
    assert row["internal_url"] == "http://svc:8080"


async def test_update_gateway_probe_running(store_a, monkeypatch):
    monkeypatch.setattr(gateway_tool, "_is_docker", lambda: False)
    monkeypatch.setattr(gateway_tool, "_probe_url", lambda url, timeout=2.0: True)
    await register_service(store_a, name="svc", port=8080)
    result = await update_service_gateway(store_a, name="svc", probe=True)
    assert result["status"] == "running"
    assert result["probe"]["external"] is True


async def test_update_gateway_probe_stopped(store_a, monkeypatch):
    monkeypatch.setattr(gateway_tool, "_is_docker", lambda: False)
    monkeypatch.setattr(gateway_tool, "_probe_url", lambda url, timeout=2.0: False)
    await register_service(store_a, name="svc", port=8080)
    result = await update_service_gateway(store_a, name="svc", probe=True)
    assert result["status"] == "stopped"


async def test_update_gateway_explicit_urls(store_a):
    await register_service(store_a, name="svc", port=8080)
    result = await update_service_gateway(
        store_a,
        name="svc",
        internal_url="http://ctr:9000",
        external_url="http://localhost:27000",
        host="1.2.3.4",
        port=27000,
        probe=False,
    )
    assert result["internal_url"] == "http://ctr:9000"
    assert result["external_url"] == "http://localhost:27000"


# ── sync_registry ─────────────────────────────────────────────────────────────
async def test_sync_registry_docker_missing_empty_ranges(store_a, monkeypatch):
    def _boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(gateway_tool.subprocess, "run", _boom)
    # port_ranges="" é falsy → sync_registry cai no default "8000-8100"; stub evita scan real.
    monkeypatch.setattr(gateway_tool, "_scan_port_ranges", _no_port_scan)
    result = await sync_registry(store_a, port_ranges="", service_names=None, probe_health=False)
    assert result["context"] == "local"
    assert result["docker_scan"]["error"] == "docker not found"
    assert result["total_upserted"] == 0


async def test_sync_registry_with_docker_and_names(store_a, monkeypatch):
    ctr = json.dumps({"ID": "id1", "Names": "web", "Ports": "0.0.0.0:8080->80/tcp", "Image": "nginx"})
    monkeypatch.setattr(gateway_tool.subprocess, "run", lambda *a, **k: _FakeProc(stdout=ctr + "\n"))
    monkeypatch.setattr(gateway_tool, "_probe_url", lambda url, timeout=2.0: True)
    monkeypatch.setattr(gateway_tool, "_scan_port_ranges", _no_port_scan)
    await register_service(store_a, name="named", port=9090)
    result = await sync_registry(
        store_a, port_ranges="", service_names=["named"], include_docker=True, probe_health=True
    )
    assert result["docker_scan"]["upserted"] == 1
    assert result["name_scan"]["found"] == 1
    # o container foi persistido com internal_url derivada
    row = await store_a.get("web")
    assert row["internal_url"] == "http://web:80"


# ── _scan_port_ranges / _scan_by_names (unidade) ──────────────────────────────
async def test_scan_port_ranges_identifies(store_a, monkeypatch):
    monkeypatch.setattr(gateway_tool, "_probe_url", lambda url, timeout=1.5: True)
    monkeypatch.setattr(gateway_tool, "_identify_service", lambda port, timeout=1.5: "svc-found")
    result = await _scan_port_ranges(store_a, "8000-8001", probe=True)
    assert result["scanned"] == 2
    assert result["found"] == 2
    assert (await store_a.get("svc-found")) is not None


async def test_scan_port_ranges_bad_range(store_a, monkeypatch):
    monkeypatch.setattr(gateway_tool, "_identify_service", lambda port, timeout=1.5: None)
    result = await _scan_port_ranges(store_a, "bad-range,7000", probe=False)
    # 'bad-range' ignorado; 7000 escaneado mas não identificado
    assert result["scanned"] == 1
    assert result["found"] == 0


async def test_scan_by_names(store_a, monkeypatch):
    monkeypatch.setattr(gateway_tool, "_is_docker", lambda: False)
    monkeypatch.setattr(gateway_tool, "_probe_url", lambda url, timeout=2.0: True)
    await register_service(store_a, name="svc", port=8080)
    result = await _scan_by_names(store_a, ["svc"], probe=True)
    assert result["found"] == 1
    assert result["services"][0]["kind"] == "external"
