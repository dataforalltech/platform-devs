"""Testes das tools de launch/stop de serviços.

Herméticos: subprocess (Popen/run), httpx e time.sleep são mockados.
Nenhum processo ou container é realmente iniciado.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tools import launch_tool
from src.tools.launch_tool import launch_service, stop_service

from .conftest import make_service


def _healthy_client():
    """Mock httpx.Client cujo GET responde 200 (serviço saudável)."""
    resp = MagicMock()
    resp.status_code = 200
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = resp
    cls = MagicMock(return_value=client)
    return cls


# ── validação ─────────────────────────────────────────────────────────────── #


def test_launch_invalid_mode(store):
    result = launch_service(store, name="x", mode="k8s", port=8080)
    assert result["error"] == "InvalidMode"


def test_launch_empty_name(store):
    result = launch_service(store, name="", mode="uvicorn", port=8080)
    assert result["error"] == "ValidationError"


def test_launch_invalid_port(store):
    result = launch_service(store, name="x", mode="uvicorn", port=0)
    assert result["error"] == "ValidationError"


def test_launch_uvicorn_requires_app(store):
    result = launch_service(store, name="x", mode="uvicorn", port=8080)
    assert result["error"] == "ValidationError"
    assert "app" in result["details"]


def test_launch_docker_requires_image(store):
    result = launch_service(store, name="x", mode="docker", port=8080)
    assert result["error"] == "ValidationError"
    assert "image" in result["details"]


# ── uvicorn ───────────────────────────────────────────────────────────────── #


def test_launch_uvicorn_success(store):
    proc = MagicMock()
    proc.pid = 4321
    with (
        patch("src.tools.launch_tool.subprocess.Popen", return_value=proc),
        patch.object(launch_tool.httpx, "Client", _healthy_client()),
    ):
        result = launch_service(store, name="svc-u", mode="uvicorn", port=8080, app="pkg.main:app")
    assert result["registered"] is True
    assert result["healthy"] is True
    assert result["pid"] == 4321
    assert result["status"] == "running"
    row = store.get("svc-u")
    assert row["type"] == "process"
    assert row["pid"] == 4321


def test_launch_uvicorn_not_found(store):
    with patch("src.tools.launch_tool.subprocess.Popen", side_effect=FileNotFoundError):
        result = launch_service(store, name="svc-u", mode="uvicorn", port=8080, app="pkg.main:app")
    assert result["error"] == "UvicornNotFound"


# ── docker ────────────────────────────────────────────────────────────────── #


def test_launch_docker_success(store):
    run_result = MagicMock()
    run_result.returncode = 0
    run_result.stdout = "abcdef1234567890\n"
    run_result.stderr = ""
    with (
        patch("src.tools.launch_tool.subprocess.run", return_value=run_result),
        patch.object(launch_tool.httpx, "Client", _healthy_client()),
    ):
        result = launch_service(store, name="svc-d", mode="docker", port=8080, image="nginx:latest")
    assert result["registered"] is True
    assert result["container_id"] == "abcdef123456"
    row = store.get("svc-d")
    assert row["type"] == "docker"
    assert row["internal_url"] == "http://svc-d:8080"


def test_launch_docker_run_failed(store):
    run_result = MagicMock()
    run_result.returncode = 1
    run_result.stdout = ""
    run_result.stderr = "boom"
    with patch("src.tools.launch_tool.subprocess.run", return_value=run_result):
        result = launch_service(store, name="svc-d", mode="docker", port=8080, image="nginx:latest")
    assert result["error"] == "DockerRunFailed"


def test_launch_docker_not_found(store):
    with patch("src.tools.launch_tool.subprocess.run", side_effect=FileNotFoundError):
        result = launch_service(store, name="svc-d", mode="docker", port=8080, image="nginx:latest")
    assert result["error"] == "DockerNotFound"


# ── docker-compose ────────────────────────────────────────────────────────── #


def test_launch_compose_success(store):
    up_result = MagicMock()
    up_result.returncode = 0
    up_result.stdout = ""
    up_result.stderr = "Started"
    ps_result = MagicMock()
    ps_result.stdout = "container123456\n"
    with (
        patch(
            "src.tools.launch_tool.subprocess.run",
            side_effect=[up_result, ps_result],
        ),
        patch.object(launch_tool.httpx, "Client", _healthy_client()),
    ):
        result = launch_service(store, name="svc-c", mode="docker-compose", port=8080)
    assert result["registered"] is True
    assert result["container_id"] == "container123"


def test_launch_compose_failed(store):
    up_result = MagicMock()
    up_result.returncode = 1
    up_result.stdout = ""
    up_result.stderr = "compose error"
    with patch("src.tools.launch_tool.subprocess.run", return_value=up_result):
        result = launch_service(store, name="svc-c", mode="docker-compose", port=8080)
    assert result["error"] == "ComposeUpFailed"


# ── health timeout path ───────────────────────────────────────────────────── #


def test_launch_unhealthy_marks_stopped(store):
    proc = MagicMock()
    proc.pid = 999
    # Client cujo GET sempre lança → nunca fica healthy; wait_timeout=0 evita loop/sleep
    bad_client = MagicMock()
    bad_client.__enter__ = MagicMock(return_value=bad_client)
    bad_client.__exit__ = MagicMock(return_value=False)
    bad_client.get.side_effect = Exception("refused")
    with (
        patch("src.tools.launch_tool.subprocess.Popen", return_value=proc),
        patch.object(launch_tool.httpx, "Client", MagicMock(return_value=bad_client)),
        patch("src.tools.launch_tool.time.sleep", return_value=None),
    ):
        result = launch_service(
            store,
            name="svc-bad",
            mode="uvicorn",
            port=8080,
            app="pkg:app",
            wait_timeout=0,
        )
    assert result["healthy"] is False
    assert result["status"] == "stopped"


# ── stop_service ──────────────────────────────────────────────────────────── #


def test_stop_service_not_found(store):
    result = stop_service(store, name="ghost")
    assert result["error"] == "not_found"


def test_stop_service_docker(store):
    make_service(store, name="svc-d", port=8080, type_="docker")
    run_result = MagicMock()
    run_result.returncode = 0
    run_result.stdout = "svc-d"
    run_result.stderr = ""
    with patch("src.tools.launch_tool.subprocess.run", return_value=run_result):
        result = stop_service(store, name="svc-d")
    assert result["stopped"] is True
    assert store.get("svc-d")["status"] == "stopped"


def test_stop_service_process_kills_pid(store):
    make_service(store, name="svc-p", port=8080, type_="process")
    store.upsert("svc-p", {"pid": 12345})
    with patch("src.tools.launch_tool.os.kill", return_value=None) as mock_kill:
        result = stop_service(store, name="svc-p")
    assert result["stopped"] is True
    mock_kill.assert_called_once()
    assert store.get("svc-p")["status"] == "stopped"


def test_stop_service_process_no_pid(store):
    make_service(store, name="svc-p", port=8080, type_="process")
    result = stop_service(store, name="svc-p")
    assert result["stopped"] is False
    assert "pid" in result["error"]


def test_stop_service_process_already_gone(store):
    make_service(store, name="svc-p", port=8080, type_="process")
    store.upsert("svc-p", {"pid": 12345})
    with patch("src.tools.launch_tool.os.kill", side_effect=ProcessLookupError):
        result = stop_service(store, name="svc-p")
    assert result["stopped"] is True


def test_stop_service_unsupported_type(store):
    make_service(store, name="svc-x", port=8080, type_="unknown")
    result = stop_service(store, name="svc-x")
    assert result["stopped"] is False
