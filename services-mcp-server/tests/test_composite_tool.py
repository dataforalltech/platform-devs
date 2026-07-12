"""Tools compostas contra MySQL real: service_status, list_environments e reload_service.

check_health (HTTP) e o subprocess do reload são o único duplo — o banco é real (FID-02).
"""

from __future__ import annotations

import subprocess

import pytest

from src.tools import composite_tool, discovery_tool
from src.tools.composite_tool import list_environments, reload_service, service_status
from src.tools.registry_tool import register_service

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_code: int = 200, boom: bool = False) -> None:
        self._status = status_code
        self._boom = boom

    def __call__(self, *_a, **_k) -> _FakeClient:
        return self

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def get(self, _url: str) -> _FakeResp:
        if self._boom:
            raise RuntimeError("connection refused")
        return _FakeResp(self._status)


def _patch_health(monkeypatch, *, status_code: int = 200, boom: bool = False) -> None:
    monkeypatch.setattr(discovery_tool.httpx, "Client", _FakeClient(status_code, boom))


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── service_status ────────────────────────────────────────────────────────────
async def test_service_status_not_found(store_a):
    result = await service_status(store_a, name="ghost")
    assert result == {"name": "ghost", "found": False, "overall_status": "unknown"}


async def test_service_status_healthy(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=200)
    await register_service(store_a, name="svc", port=8080)
    result = await service_status(store_a, name="svc", timeout=0.1)
    assert result["overall_status"] == "healthy"
    assert result["health"]["healthy"] is True


async def test_service_status_unhealthy(store_a, monkeypatch):
    _patch_health(monkeypatch, boom=True)
    await register_service(store_a, name="svc", port=8080)
    result = await service_status(store_a, name="svc", timeout=0.1)
    assert result["overall_status"] == "unhealthy"


# ── list_environments ─────────────────────────────────────────────────────────
async def test_list_environments_groups_and_counts(store_a):
    await register_service(store_a, name="a", port=1, environment="local", status="running")
    await register_service(store_a, name="b", port=2, environment="local", status="stopped")
    await register_service(store_a, name="c", port=3, environment="hml")

    result = await list_environments(store_a)
    assert result["total_services"] == 3
    assert result["total_environments"] == 2
    by_env = {e["environment"]: e for e in result["environments"]}
    assert by_env["local"]["total"] == 2
    assert by_env["local"]["running"] == 1
    assert by_env["local"]["stopped"] == 1
    assert by_env["hml"]["unknown"] == 1


# ── reload_service ────────────────────────────────────────────────────────────
async def test_reload_not_found(store_a):
    assert (await reload_service(store_a, name="ghost"))["error"] == "not_found"


async def test_reload_unknown_type_rechecks_health(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=200)
    await register_service(store_a, name="svc", port=8080, type="unknown")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["reload_method"] == "health_recheck"
    assert result["success"] is True
    assert result["health_after_reload"]["healthy"] is True


async def test_reload_docker_success(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=200)
    monkeypatch.setattr(
        composite_tool.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout="svc")
    )
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["reload_method"] == "docker_restart"
    assert result["reload_output"] == "svc"
    assert result["success"] is True


async def test_reload_docker_not_installed(store_a, monkeypatch):
    _patch_health(monkeypatch, boom=True)

    def _boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(composite_tool.subprocess, "run", _boom)
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["success"] is False
    assert "Docker" in result["reload_error"]


async def test_reload_docker_nonzero_exit(store_a, monkeypatch):
    _patch_health(monkeypatch, boom=True)
    monkeypatch.setattr(
        composite_tool.subprocess,
        "run",
        lambda *a, **k: _FakeProc(returncode=1, stderr="no such container"),
    )
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["success"] is False
    assert "no such container" in result["reload_error"]


async def test_reload_docker_timeout(store_a, monkeypatch):
    _patch_health(monkeypatch, boom=True)

    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=30)

    monkeypatch.setattr(composite_tool.subprocess, "run", _timeout)
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["success"] is False


async def test_reload_process_no_pid_on_port(store_a, monkeypatch):
    _patch_health(monkeypatch, boom=True)
    import psutil

    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": [])
    await register_service(store_a, name="svc", port=8080, type="process")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["reload_method"] == "process_kill"
    assert result["success"] is False
    assert "Nenhum processo" in result["reload_error"]


async def test_reload_remote_no_endpoint(store_a, monkeypatch):
    _patch_health(monkeypatch, boom=True)
    import urllib.request

    def _boom(*_a, **_k):
        raise OSError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    await register_service(store_a, name="svc", port=8080, type="remote")
    result = await reload_service(store_a, name="svc", wait_seconds=0, health_timeout=0.1)
    assert result["reload_method"] == "http_reload"
    assert result["success"] is False
