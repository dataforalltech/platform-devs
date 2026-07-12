"""Discovery: scan_docker/scan_processes/check_health/check_all_health.

Banco real (FID-02); docker/psutil/httpx são o único duplo (serviços externos ao store).
"""

from __future__ import annotations

import json
import subprocess

import httpx
import pytest

from src.tools import discovery_tool
from src.tools.discovery_tool import (
    _deploy_mode,
    _detect_runtime,
    _docker_inspect_runtime,
    _host_os,
    _parse_first_port,
    check_all_health,
    check_health,
    scan_docker,
    scan_processes,
)
from src.tools.registry_tool import register_service

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


def _patch_health(monkeypatch, *, status_code: int = 200, exc: Exception | None = None) -> None:
    monkeypatch.setattr(discovery_tool.httpx, "Client", _FakeClient(status_code, exc))


# ── helpers puros ─────────────────────────────────────────────────────────────
def test_parse_first_port():
    assert _parse_first_port("0.0.0.0:8080->80/tcp, :::8080->80/tcp") == 8080
    assert _parse_first_port("") is None
    assert _parse_first_port("80/tcp") is None


def test_detect_runtime_and_deploy_mode():
    assert _detect_runtime("python -m uvicorn main:app") == "uvicorn"
    assert _detect_runtime("gunicorn app:app") == "gunicorn"
    assert _detect_runtime("node server.js") == "node"
    assert _detect_runtime("mystery-binary") == "unknown"
    assert _deploy_mode("uvicorn") == "asgi"
    assert _deploy_mode("gunicorn") == "wsgi"
    assert _deploy_mode("unknown") == "unknown"


def test_host_os_keys():
    info = _host_os()
    assert set(info) == {"os_name", "os_release"}


def test_docker_inspect_runtime_empty():
    assert _docker_inspect_runtime([]) == {}


def test_docker_inspect_runtime_parses(monkeypatch):
    inspect_line = json.dumps(
        {"Id": "abc123def456xxx", "Config": {"Entrypoint": ["uvicorn"], "Cmd": ["app"], "Hostname": "h1"}}
    )
    monkeypatch.setattr(
        discovery_tool.subprocess, "run", lambda *a, **k: _FakeProc(stdout=inspect_line + "\n")
    )
    info = _docker_inspect_runtime(["abc123def456xxx"])
    assert info["abc123def456"]["runtime"] == "uvicorn"
    assert info["abc123def456"]["deploy_mode"] == "asgi"
    assert info["abc123def456"]["hostname"] == "h1"


def test_docker_inspect_runtime_docker_missing(monkeypatch):
    def _boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(discovery_tool.subprocess, "run", _boom)
    assert _docker_inspect_runtime(["x"]) == {}


# ── scan_docker ───────────────────────────────────────────────────────────────
async def test_scan_docker_not_installed(store_a, monkeypatch):
    def _boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(discovery_tool.subprocess, "run", _boom)
    result = await scan_docker(store_a)
    assert result["docker_error"] == "docker not found"
    assert result["scanned"] == 0


async def test_scan_docker_timeout(store_a, monkeypatch):
    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=10)

    monkeypatch.setattr(discovery_tool.subprocess, "run", _timeout)
    result = await scan_docker(store_a, timeout=10)
    assert "timeout" in result["docker_error"]


async def test_scan_docker_nonzero(store_a, monkeypatch):
    monkeypatch.setattr(
        discovery_tool.subprocess, "run", lambda *a, **k: _FakeProc(returncode=1, stderr="daemon down")
    )
    result = await scan_docker(store_a)
    assert result["docker_error"] == "daemon down"


async def test_scan_docker_success(store_a, monkeypatch):
    ps_line = json.dumps(
        {
            "ID": "abc123def456",
            "Names": "myctr",
            "Ports": "0.0.0.0:8080->80/tcp",
            "Image": "nginx:latest",
            "Command": "nginx -g",
        }
    )
    inspect_line = json.dumps(
        {"Id": "abc123def456", "Config": {"Entrypoint": ["uvicorn"], "Cmd": ["app"], "Hostname": "h1"}}
    )

    def _run(cmd, *_a, **_k):
        if "inspect" in cmd:
            return _FakeProc(stdout=inspect_line + "\n")
        return _FakeProc(stdout=ps_line + "\n")

    monkeypatch.setattr(discovery_tool.subprocess, "run", _run)
    result = await scan_docker(store_a)
    assert result["scanned"] == 1
    assert result["upserted"] == 1
    assert result["containers"][0]["name"] == "myctr"
    assert result["containers"][0]["port"] == 8080
    assert result["containers"][0]["runtime"] == "uvicorn"
    # persistiu no registry
    row = await store_a.get("myctr")
    assert row is not None


# ── scan_processes ────────────────────────────────────────────────────────────
class _Addr:
    def __init__(self, port: int) -> None:
        self.port = port


class _Conn:
    def __init__(self, port: int, pid: int | None, status: str = "LISTEN") -> None:
        self.laddr = _Addr(port)
        self.pid = pid
        self.status = status


class _FakePsProcess:
    def __init__(self, _pid: int) -> None:
        pass

    def name(self) -> str:
        return "python3"

    def cmdline(self) -> list[str]:
        return ["python3", "-m", "uvicorn", "main:app"]


async def test_scan_processes(store_a, monkeypatch):
    import psutil

    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda kind="inet": [_Conn(8080, 111), _Conn(500, 222), _Conn(8080, 333)],
    )
    monkeypatch.setattr(psutil, "Process", _FakePsProcess)
    result = await scan_processes(store_a, min_port=1024)
    # porta 500 filtrada (< min_port); 8080 deduplicada
    assert result["total"] == 1
    assert result["processes"][0]["port"] == 8080
    assert result["processes"][0]["runtime"] == "uvicorn"
    row = await store_a.get("proc-8080")
    assert row is not None


async def test_scan_processes_permission_denied(store_a, monkeypatch):
    import psutil

    def _denied(kind="inet"):
        raise psutil.AccessDenied

    monkeypatch.setattr(psutil, "net_connections", _denied)
    result = await scan_processes(store_a)
    assert result["error"] == "permission_denied"


# ── check_health ──────────────────────────────────────────────────────────────
async def test_check_health_not_found(store_a):
    result = await check_health(store_a, name="ghost")
    assert result["error"] == "not_found"
    assert result["healthy"] is False


async def test_check_health_healthy(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=200)
    await register_service(store_a, name="svc", port=8080)
    result = await check_health(store_a, name="svc", timeout=0.1)
    assert result["healthy"] is True
    assert result["status_code"] == 200
    # persistiu last_check_ok
    from src.models.service import service_record

    assert service_record(await store_a.get("svc"))["last_check_ok"] is True


async def test_check_health_unhealthy_status(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=503)
    await register_service(store_a, name="svc", port=8080)
    result = await check_health(store_a, name="svc", timeout=0.1)
    assert result["healthy"] is False
    assert result["status_code"] == 503


async def test_check_health_timeout(store_a, monkeypatch):
    _patch_health(monkeypatch, exc=httpx.TimeoutException("t"))
    await register_service(store_a, name="svc", port=8080)
    result = await check_health(store_a, name="svc", timeout=0.1)
    assert result["healthy"] is False
    assert result["error"] == "timeout"


async def test_check_health_generic_error(store_a, monkeypatch):
    _patch_health(monkeypatch, exc=RuntimeError("boom"))
    await register_service(store_a, name="svc", port=8080)
    result = await check_health(store_a, name="svc", timeout=0.1)
    assert result["healthy"] is False
    assert "boom" in result["error"]


async def test_check_health_uses_url_field(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=200)
    await store_a.upsert("svc", {"url": "http://example.com/base/", "health_path": "/livez"})
    result = await check_health(store_a, name="svc", timeout=0.1)
    assert result["url_checked"] == "http://example.com/base/livez"


# ── check_all_health ──────────────────────────────────────────────────────────
async def test_check_all_health(store_a, monkeypatch):
    _patch_health(monkeypatch, status_code=200)
    await register_service(store_a, name="up", port=8080, health_path="/health")
    # serviço sem health_path é pulado
    await store_a.upsert("nohealth", {"port": 9090, "health_path": None})
    result = await check_all_health(store_a, timeout=0.1)
    assert result["total_checked"] == 1
    assert result["healthy"] == 1
    assert result["skipped"] == 1
    # status promovido para running
    assert (await store_a.get("up"))["status"] == "running"


async def test_check_all_health_marks_stopped(store_a, monkeypatch):
    _patch_health(monkeypatch, exc=RuntimeError("down"))
    await register_service(store_a, name="svc", port=8080, health_path="/health", status="running")
    await store_a.upsert("svc", {"status": "running"})
    result = await check_all_health(store_a, timeout=0.1)
    assert result["unhealthy"] == 1
    assert (await store_a.get("svc"))["status"] == "stopped"
