"""Testes de reload_service (composite tool).

Herméticos: subprocess, psutil, urllib e time.sleep são mockados.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tools import composite_tool
from src.tools.composite_tool import reload_service

from .conftest import make_service

_HEALTHY = {
    "name": "svc",
    "healthy": True,
    "status_code": 200,
    "url_checked": "http://localhost:8080/health",
    "response_ms": 5.0,
}


def test_reload_not_found(store):
    result = reload_service(store, name="ghost")
    assert result["error"] == "not_found"


def test_reload_docker_restart_success(store):
    make_service(store, name="svc", port=8080, type_="docker")
    run_result = MagicMock()
    run_result.returncode = 0
    run_result.stdout = "svc"
    run_result.stderr = ""
    with (
        patch("src.tools.composite_tool.subprocess.run", return_value=run_result),
        patch("src.tools.composite_tool.time.sleep", return_value=None),
        patch.object(composite_tool, "check_health", return_value=_HEALTHY),
    ):
        result = reload_service(store, name="svc", wait_seconds=1)
    assert result["reload_method"] == "docker_restart"
    assert result["success"] is True


def test_reload_docker_not_found(store):
    make_service(store, name="svc", port=8080, type_="docker")
    with (
        patch("src.tools.composite_tool.subprocess.run", side_effect=FileNotFoundError),
        patch("src.tools.composite_tool.time.sleep", return_value=None),
        patch.object(composite_tool, "check_health", return_value=_HEALTHY),
    ):
        result = reload_service(store, name="svc", wait_seconds=0)
    assert result["success"] is False
    assert "Docker" in result["reload_error"]


def test_reload_process_kills_pid(store):
    make_service(store, name="svc", port=8080, type_="process")

    conn = MagicMock()
    conn.laddr.port = 8080
    conn.status = "LISTEN"
    conn.pid = 4242
    proc = MagicMock()

    fake_psutil = MagicMock()
    fake_psutil.net_connections.return_value = [conn]
    fake_psutil.Process.return_value = proc
    fake_psutil.NoSuchProcess = Exception
    fake_psutil.AccessDenied = Exception

    with (
        patch.dict("sys.modules", {"psutil": fake_psutil}),
        patch("src.tools.composite_tool.time.sleep", return_value=None),
        patch.object(composite_tool, "check_health", return_value=_HEALTHY),
    ):
        result = reload_service(store, name="svc", wait_seconds=0)

    assert result["reload_method"] == "process_kill"
    proc.terminate.assert_called_once()


def test_reload_remote_http(store):
    make_service(store, name="svc", port=8080, type_="remote")

    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)

    with (
        patch("urllib.request.urlopen", return_value=resp),
        patch("src.tools.composite_tool.time.sleep", return_value=None),
        patch.object(composite_tool, "check_health", return_value=_HEALTHY),
    ):
        result = reload_service(store, name="svc", wait_seconds=0)

    assert result["reload_method"] == "http_reload"
    assert result["success"] is True


def test_reload_unknown_type(store):
    make_service(store, name="svc", port=8080, type_="unknown")
    with (
        patch("src.tools.composite_tool.time.sleep", return_value=None),
        patch.object(composite_tool, "check_health", return_value=_HEALTHY),
    ):
        result = reload_service(store, name="svc", wait_seconds=0)
    assert result["reload_method"] == "health_recheck"
    assert result["success"] is True
