"""Testes das tools de descoberta de serviços."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import psutil

from src.tools.discovery_tool import check_all_health, check_health, scan_docker, scan_processes

from .conftest import make_service

# ── scan_docker ───────────────────────────────────────────────────────────── #

_DOCKER_LINE_1 = '{"ID":"abc123","Names":"api-gateway","Image":"myimage:1.0","Ports":"0.0.0.0:8080->80/tcp"}'
_DOCKER_LINE_2 = '{"ID":"def456","Names":"worker","Image":"worker:2.0","Ports":"0.0.0.0:9000->9000/tcp"}'


def test_scan_docker_success(store):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _DOCKER_LINE_1 + "\n" + _DOCKER_LINE_2 + "\n"
    mock_result.stderr = ""

    with patch("src.tools.discovery_tool.subprocess.run", return_value=mock_result):
        result = scan_docker(store, timeout=5)

    assert result["docker_error"] is None
    assert result["scanned"] == 2
    assert result["upserted"] == 2
    assert len(result["containers"]) == 2
    ports = {c["port"] for c in result["containers"]}
    assert 8080 in ports
    assert 9000 in ports


def test_scan_docker_not_installed(store):
    with patch("src.tools.discovery_tool.subprocess.run", side_effect=FileNotFoundError):
        result = scan_docker(store, timeout=5)

    assert result["docker_error"] is not None
    assert "docker" in result["docker_error"].lower()
    assert result["scanned"] == 0
    assert result["upserted"] == 0


def test_scan_docker_no_containers(store):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("src.tools.discovery_tool.subprocess.run", return_value=mock_result):
        result = scan_docker(store, timeout=5)

    assert result["docker_error"] is None
    assert result["scanned"] == 0
    assert result["upserted"] == 0
    assert result["containers"] == []


def test_scan_docker_exit_code_nonzero(store):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Cannot connect to the Docker daemon"

    with patch("src.tools.discovery_tool.subprocess.run", return_value=mock_result):
        result = scan_docker(store, timeout=5)

    assert result["docker_error"] is not None
    assert result["upserted"] == 0


# ── scan_processes ────────────────────────────────────────────────────────── #


def _make_conn(pid: int, port: int) -> MagicMock:
    conn = MagicMock()
    conn.status = "LISTEN"
    conn.laddr = MagicMock()
    conn.laddr.port = port
    conn.pid = pid
    return conn


def test_scan_processes_success(store):
    conn1 = _make_conn(pid=1234, port=8080)
    conn2 = _make_conn(pid=5678, port=9090)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "python"
    mock_proc.cmdline.return_value = ["python", "app.py"]

    with (
        patch("src.tools.discovery_tool.psutil.net_connections", return_value=[conn1, conn2]),
        patch("src.tools.discovery_tool.psutil.Process", return_value=mock_proc),
    ):
        result = scan_processes(store, min_port=1024)

    assert result["total"] == 2
    ports = {p["port"] for p in result["processes"]}
    assert 8080 in ports
    assert 9090 in ports


def test_scan_processes_permission_denied(store):
    with patch(
        "src.tools.discovery_tool.psutil.net_connections",
        side_effect=psutil.AccessDenied(pid=0),
    ):
        result = scan_processes(store, min_port=1024)

    assert result["error"] == "permission_denied"
    assert result["total"] == 0


def test_scan_processes_filters_below_min_port(store):
    conn_low = _make_conn(pid=100, port=80)
    conn_high = _make_conn(pid=200, port=8080)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "server"
    mock_proc.cmdline.return_value = ["server"]

    with (
        patch("src.tools.discovery_tool.psutil.net_connections", return_value=[conn_low, conn_high]),
        patch("src.tools.discovery_tool.psutil.Process", return_value=mock_proc),
    ):
        result = scan_processes(store, min_port=1024)

    assert result["total"] == 1
    assert result["processes"][0]["port"] == 8080


# ── check_health ──────────────────────────────────────────────────────────── #


def test_check_health_healthy(store):
    make_service(store, name="api-gateway", port=8080)

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("src.tools.discovery_tool.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = check_health(store, name="api-gateway", timeout=2.0)

    assert result["healthy"] is True
    assert result["status_code"] == 200
    assert "localhost:8080" in result["url_checked"]
    assert "/health" in result["url_checked"]
    assert result["response_ms"] >= 0


def test_check_health_timeout(store):
    make_service(store, name="api-gateway", port=8080)

    with patch("src.tools.discovery_tool.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_client

        result = check_health(store, name="api-gateway", timeout=2.0)

    assert result["healthy"] is False
    assert result["error"] == "timeout"


def test_check_health_service_not_found(store):
    result = check_health(store, name="nonexistent", timeout=2.0)
    assert result["healthy"] is False
    assert result["error"] == "not_found"


def test_check_health_unhealthy_status_code(store):
    make_service(store, name="api-gateway", port=8080)

    mock_response = MagicMock()
    mock_response.status_code = 503

    with patch("src.tools.discovery_tool.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = check_health(store, name="api-gateway", timeout=2.0)

    assert result["healthy"] is False
    assert result["status_code"] == 503


# ── check_all_health ──────────────────────────────────────────────────────── #


def test_check_all_health_mixed(store):
    make_service(store, name="svc-healthy", port=8080)
    make_service(store, name="svc-unhealthy", port=9090)

    call_count = 0

    def fake_check_health(s, *, name, timeout):
        nonlocal call_count
        call_count += 1
        if name == "svc-healthy":
            return {"name": name, "healthy": True, "status_code": 200, "url_checked": "http://localhost:8080/health", "response_ms": 10.0}
        return {"name": name, "healthy": False, "status_code": 503, "url_checked": "http://localhost:9090/health", "response_ms": 5.0}

    with patch("src.tools.discovery_tool.check_health", side_effect=fake_check_health):
        result = check_all_health(store, timeout=2.0)

    assert result["total_checked"] == 2
    assert result["healthy"] == 1
    assert result["unhealthy"] == 1
    assert result["skipped"] == 0
    assert len(result["results"]) == 2
