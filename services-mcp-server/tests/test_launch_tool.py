"""launch_service / stop_service + polling de health.

Banco real (FID-02); subprocess (uvicorn/docker) e httpx são o único duplo.
"""

from __future__ import annotations

import subprocess

import pytest

from src.tools import launch_tool
from src.tools.launch_tool import _wait_healthy, launch_service, stop_service
from src.tools.registry_tool import register_service

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakePopen:
    def __init__(self, *_a, **_k) -> None:
        self.pid = 4242


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_code: int = 200, exc: Exception | None = None) -> None:
        self._status = status_code
        self._exc = exc

    def __call__(self, *_a, **_k) -> _FakeClient:
        return self

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def get(self, _url: str) -> _FakeResp:
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._status)


_HEALTHY = {
    "healthy": True,
    "url_checked": "http://localhost:8080/v1/health",
    "status_code": 200,
    "ready_in_ms": 5,
    "attempts": 1,
}


# ── validação ─────────────────────────────────────────────────────────────────
async def test_launch_invalid_mode(store_a):
    result = await launch_service(store_a, name="svc", mode="k8s", port=8080)
    assert result["error"] == "InvalidMode"


async def test_launch_empty_name(store_a):
    result = await launch_service(store_a, name="  ", mode="uvicorn", port=8080)
    assert result["error"] == "ValidationError"


async def test_launch_bad_port(store_a):
    result = await launch_service(store_a, name="svc", mode="uvicorn", port=0)
    assert result["error"] == "ValidationError"


async def test_launch_uvicorn_requires_app(store_a):
    result = await launch_service(store_a, name="svc", mode="uvicorn", port=8080)
    assert result["error"] == "ValidationError"
    assert "app" in result["details"]


async def test_launch_docker_requires_image(store_a):
    result = await launch_service(store_a, name="svc", mode="docker", port=8080)
    assert result["error"] == "ValidationError"


# ── uvicorn ───────────────────────────────────────────────────────────────────
async def test_launch_uvicorn_success(store_a, monkeypatch):
    monkeypatch.setattr(launch_tool.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(launch_tool, "_wait_healthy", lambda **_k: dict(_HEALTHY))
    result = await launch_service(store_a, name="svc", mode="uvicorn", port=8080, app="pkg.main:app")
    assert result["healthy"] is True
    assert result["status"] == "running"
    assert result["pid"] == 4242
    assert result["registered"] is True
    row = await store_a.get("svc")
    assert row["pid"] == 4242


async def test_launch_uvicorn_binary_missing(store_a, monkeypatch):
    def _boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(launch_tool.subprocess, "Popen", _boom)
    result = await launch_service(store_a, name="svc", mode="uvicorn", port=8080, app="pkg:app")
    assert result["error"] == "UvicornNotFound"


# ── docker ────────────────────────────────────────────────────────────────────
async def test_launch_docker_success(store_a, monkeypatch):
    monkeypatch.setattr(
        launch_tool.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout="ctr12345")
    )
    monkeypatch.setattr(launch_tool, "_wait_healthy", lambda **_k: dict(_HEALTHY))
    result = await launch_service(store_a, name="svc", mode="docker", port=8080, image="nginx:latest")
    assert result["mode"] == "docker"
    assert result["internal_url"] == "http://svc:8080"
    assert result["container_id"] == "ctr12345"
    row = await store_a.get("svc")
    assert row["type"] == "docker"


async def test_launch_docker_run_failed(store_a, monkeypatch):
    monkeypatch.setattr(
        launch_tool.subprocess, "run", lambda *a, **k: _FakeProc(returncode=1, stderr="pull error")
    )
    result = await launch_service(store_a, name="svc", mode="docker", port=8080, image="img")
    assert result["error"] == "DockerRunFailed"


# ── docker-compose ────────────────────────────────────────────────────────────
async def test_launch_compose_success(store_a, monkeypatch):
    monkeypatch.setattr(launch_tool.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0))
    monkeypatch.setattr(launch_tool, "_get_compose_container_id", lambda service, cwd: "cid98765")
    monkeypatch.setattr(launch_tool, "_wait_healthy", lambda **_k: {"healthy": False, "url_checked": "u"})
    result = await launch_service(
        store_a, name="svc", mode="docker-compose", port=8080, compose_service="svc"
    )
    assert result["mode"] == "docker-compose"
    assert result["status"] == "stopped"  # health falhou → stopped


# ── _wait_healthy ─────────────────────────────────────────────────────────────
def test_wait_healthy_success(monkeypatch):
    monkeypatch.setattr(launch_tool.httpx, "Client", _FakeClient(200))
    result = _wait_healthy(
        url="http://localhost:8080",
        health_path="/v1/health",
        wait_timeout=5,
        check_interval=0.01,
        http_timeout=0.1,
    )
    assert result["healthy"] is True
    assert result["status_code"] == 200


def test_wait_healthy_timeout():
    result = _wait_healthy(
        url="http://localhost:8080",
        health_path="/v1/health",
        wait_timeout=0,
        check_interval=0.01,
        http_timeout=0.1,
    )
    assert result["healthy"] is False
    assert "timeout" in result["error"]


# ── stop_service ──────────────────────────────────────────────────────────────
async def test_stop_not_found(store_a):
    assert (await stop_service(store_a, name="ghost"))["error"] == "not_found"


async def test_stop_docker(store_a, monkeypatch):
    monkeypatch.setattr(launch_tool.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout="svc"))
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await stop_service(store_a, name="svc")
    assert result["stopped"] is True
    assert (await store_a.get("svc"))["status"] == "stopped"


async def test_stop_docker_timeout(store_a, monkeypatch):
    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=10)

    monkeypatch.setattr(launch_tool.subprocess, "run", _timeout)
    await register_service(store_a, name="svc", port=8080, type="docker")
    result = await stop_service(store_a, name="svc")
    assert result["stopped"] is False
    assert "error" in result


async def test_stop_process(store_a, monkeypatch):
    killed: dict[str, int] = {}

    def _kill(pid, sig):
        killed["pid"] = pid

    monkeypatch.setattr(launch_tool.os, "kill", _kill)
    await store_a.upsert("svc", {"port": 8080, "type": "process", "pid": 5555})
    result = await stop_service(store_a, name="svc", mode="process")
    assert result["stopped"] is True
    assert killed["pid"] == 5555


async def test_stop_process_no_pid(store_a):
    await register_service(store_a, name="svc", port=8080, type="process")
    result = await stop_service(store_a, name="svc")
    assert result["stopped"] is False
    assert "pid" in result["error"]


async def test_stop_process_already_gone(store_a, monkeypatch):
    def _kill(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(launch_tool.os, "kill", _kill)
    await store_a.upsert("svc", {"port": 8080, "type": "process", "pid": 5555})
    result = await stop_service(store_a, name="svc", mode="process")
    assert result["stopped"] is True
    assert "note" in result


async def test_stop_unsupported_type(store_a):
    await register_service(store_a, name="svc", port=8080, type="remote")
    result = await stop_service(store_a, name="svc")
    assert result["stopped"] is False
