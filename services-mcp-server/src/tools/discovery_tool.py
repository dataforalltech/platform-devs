"""Tools de descoberta de servicos: docker, processos e health check."""

from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from typing import Any

import httpx
import psutil

from ..db.store import ServiceStore


def _parse_first_port(ports_str: str) -> int | None:
    """Extrai a primeira porta do campo Ports do docker ps.

    Exemplo: '0.0.0.0:8080->80/tcp, :::8080->80/tcp' -> 8080
    """
    if not ports_str:
        return None
    match = re.search(r":(\d+)->", ports_str)
    if match:
        return int(match.group(1))
    return None


# ── Deteccao de runtime ───────────────────────────────────────────────────────

# Padroes para detectar runtime a partir de cmdline / command / imagem
_RUNTIME_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\buvicorn\b",    re.IGNORECASE), "uvicorn"),
    (re.compile(r"\bgunicorn\b",   re.IGNORECASE), "gunicorn"),
    (re.compile(r"\bhypercorn\b",  re.IGNORECASE), "hypercorn"),
    (re.compile(r"\bdaphne\b",     re.IGNORECASE), "daphne"),
    (re.compile(r"\bwaitress\b",   re.IGNORECASE), "waitress"),
    (re.compile(r"\bnext\b|\bnpm\b|\bnode\b", re.IGNORECASE), "node"),
    (re.compile(r"\bjava\b|-jar\b", re.IGNORECASE), "java"),
    (re.compile(r"\bnginx\b",      re.IGNORECASE), "nginx"),
    (re.compile(r"\bcaddy\b",      re.IGNORECASE), "caddy"),
    (re.compile(r"\bpython\b|\bpython3\b", re.IGNORECASE), "python"),
    (re.compile(r"\bflask\b",      re.IGNORECASE), "flask"),
    (re.compile(r"\bfastapi\b",    re.IGNORECASE), "fastapi"),
]

# Deploy mode a partir de runtime
_DEPLOY_MODE_MAP: dict[str, str] = {
    "uvicorn":   "asgi",
    "gunicorn":  "wsgi",
    "hypercorn": "asgi",
    "daphne":    "asgi",
    "waitress":  "wsgi",
    "node":      "node",
    "java":      "jvm",
    "nginx":     "proxy",
    "caddy":     "proxy",
    "python":    "script",
    "flask":     "wsgi",
    "fastapi":   "asgi",
}


def _detect_runtime(text: str) -> str:
    """Detecta o runtime a partir de uma string de comando/imagem."""
    for pattern, runtime in _RUNTIME_PATTERNS:
        if pattern.search(text):
            return runtime
    return "unknown"


def _deploy_mode(runtime: str) -> str:
    return _DEPLOY_MODE_MAP.get(runtime, "unknown")


def _host_os() -> dict[str, str]:
    """Retorna info do OS do host onde o MCP esta rodando."""
    return {
        "os_name": platform.system().lower(),      # linux | windows | darwin
        "os_release": platform.release(),           # ex: 5.15.0-78-generic | 11 | 23.4.0
    }


def _docker_inspect_runtime(container_ids: list[str], timeout: int = 8) -> dict[str, dict]:
    """Faz docker inspect em lote e retorna {id: {runtime, os_name, os_release, hostname}}."""
    if not container_ids:
        return {}
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .}}", *container_ids],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    info: dict[str, dict] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        cid = data.get("Id", "")[:12]
        config = data.get("Config", {})
        host_config = data.get("HostConfig", {})

        # Comando de entrypoint + cmd
        entry = config.get("Entrypoint") or []
        cmd   = config.get("Cmd") or []
        full_cmd = " ".join(entry + cmd)

        runtime = _detect_runtime(full_cmd)

        # OS vem do host via platform (containers Linux compartilham kernel)
        host_os = _host_os()

        # Hostname do container
        hostname = config.get("Hostname", "")

        info[cid] = {
            "runtime":     runtime,
            "os_name":     host_os["os_name"],
            "os_release":  host_os["os_release"],
            "hostname":    hostname,
            "deploy_mode": _deploy_mode(runtime),
            "full_cmd":    full_cmd,
        }
    return info


def scan_docker(store: ServiceStore, *, timeout: int = 10) -> dict[str, Any]:
    """Executa docker ps + docker inspect e sincroniza registry.

    Campos capturados por container:
      - type, status, container_name, port, image
      - runtime     : uvicorn | gunicorn | node | java | nginx | ...
      - deploy_mode : asgi | wsgi | node | jvm | proxy | docker
      - os_name     : linux | windows | darwin (do host)
      - os_release  : versao do kernel/OS do host
      - hostname    : hostname do container
    """
    try:
        ps_result = subprocess.run(
            ["docker", "ps", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {"scanned": 0, "upserted": 0, "containers": [], "docker_error": "docker not found"}
    except subprocess.TimeoutExpired:
        return {"scanned": 0, "upserted": 0, "containers": [], "docker_error": f"docker ps timeout ({timeout}s)"}

    if ps_result.returncode != 0:
        return {
            "scanned": 0, "upserted": 0, "containers": [],
            "docker_error": ps_result.stderr.strip() or f"exit {ps_result.returncode}",
        }

    ps_lines = [l.strip() for l in ps_result.stdout.splitlines() if l.strip()]
    ps_data: list[dict] = []
    for line in ps_lines:
        try:
            ps_data.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Batch inspect para capturar entrypoint/cmd/hostname
    container_ids = [d.get("ID", "") for d in ps_data if d.get("ID")]
    inspect_map = _docker_inspect_runtime(container_ids, timeout=timeout)

    host_os = _host_os()
    containers: list[dict[str, Any]] = []
    upserted = 0

    for cdata in ps_data:
        container_name = cdata.get("Names", "").lstrip("/")
        ports_str = cdata.get("Ports", "")
        port = _parse_first_port(ports_str)
        image = cdata.get("Image", "")
        cid = cdata.get("ID", "")[:12]

        inspect = inspect_map.get(cid, {})

        # Runtime: tenta inspect primeiro, depois Command do docker ps, depois imagem
        ps_command = cdata.get("Command", "")
        runtime = (
            inspect.get("runtime")
            or _detect_runtime(ps_command)
            or _detect_runtime(image)
            or "docker"
        )
        if runtime == "unknown":
            runtime = "docker"

        deploy_mode = inspect.get("deploy_mode") or _deploy_mode(runtime)
        if deploy_mode == "unknown":
            deploy_mode = "docker"

        hostname = inspect.get("hostname") or container_name

        fields: dict[str, Any] = {
            "host": "localhost",
            "type": "docker",
            "status": "running",
            "container_name": container_name,
            "runtime": runtime,
            "deploy_mode": deploy_mode,
            "os_name": inspect.get("os_name") or host_os["os_name"],
            "os_release": inspect.get("os_release") or host_os["os_release"],
            "hostname": hostname,
            "metadata": {
                "image": image,
                "ports_raw": ports_str,
                "command": ps_command,
            },
        }
        if port is not None:
            fields["port"] = port

        svc_name = container_name or f"docker-{cid}"
        store.upsert(svc_name, fields)
        upserted += 1

        containers.append({
            "name": svc_name,
            "port": port,
            "image": image,
            "runtime": runtime,
            "deploy_mode": deploy_mode,
            "hostname": hostname,
            "os_name": fields["os_name"],
        })

    return {
        "scanned": len(ps_data),
        "upserted": upserted,
        "containers": containers,
        "docker_error": None,
    }


def scan_processes(store: ServiceStore, *, min_port: int = 1024) -> dict[str, Any]:
    """Usa psutil para listar processos em LISTEN com porta >= min_port.

    Campos capturados por processo:
      - pid, name, port, cmdline
      - runtime     : uvicorn | gunicorn | node | java | python | ...
      - deploy_mode : asgi | wsgi | node | jvm | script | ...
      - os_name / os_release : do host atual
      - hostname    : hostname da maquina
    """
    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        return {"error": "permission_denied", "total": 0, "processes": []}

    host_os = _host_os()
    hostname = platform.node()

    processes: list[dict[str, Any]] = []
    seen_ports: set[int] = set()

    for conn in connections:
        if conn.status != "LISTEN":
            continue
        laddr = conn.laddr
        if not laddr:
            continue
        port = laddr.port
        if port < min_port or port in seen_ports:
            continue
        seen_ports.add(port)

        pid = conn.pid
        proc_name = ""
        cmdline = ""
        if pid:
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                cmdline = " ".join(proc.cmdline())
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        # Detecta runtime pelo cmdline completo
        runtime = _detect_runtime(cmdline) if cmdline else _detect_runtime(proc_name)
        if runtime == "unknown" and proc_name:
            runtime = proc_name.lower().split(".")[0]  # ex: "python3" -> "python3"

        deploy_mode = _deploy_mode(runtime)

        entry: dict[str, Any] = {
            "pid": pid,
            "name": proc_name,
            "port": port,
            "cmdline": cmdline,
            "runtime": runtime,
            "deploy_mode": deploy_mode,
            "os_name": host_os["os_name"],
            "os_release": host_os["os_release"],
            "hostname": hostname,
            "status": "running",
        }
        processes.append(entry)

        # Registra no store com as informacoes de runtime
        svc_name = f"proc-{port}"
        store.upsert(svc_name, {
            "host": "localhost",
            "port": port,
            "pid": pid,
            "type": "process",
            "status": "running",
            "runtime": runtime,
            "deploy_mode": deploy_mode,
            "os_name": host_os["os_name"],
            "os_release": host_os["os_release"],
            "hostname": hostname,
            "metadata": {"proc_name": proc_name, "cmdline": cmdline[:512]},
        })

    return {"total": len(processes), "processes": processes}


def check_health(
    store: ServiceStore,
    *,
    name: str,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Realiza HTTP GET no health endpoint do serviço e atualiza o store."""
    row = store.get(name)
    if row is None:
        return {"error": "not_found", "name": name, "healthy": False}

    host = row.get("host") or "localhost"
    port = row.get("port")
    url_base = row.get("url") or (f"http://{host}:{port}" if port else f"http://{host}")
    health_path = row.get("health_path") or "/health"
    url_checked = url_base.rstrip("/") + health_path

    start = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url_checked)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        healthy = response.status_code < 400
        store.update_check(name, healthy)
        return {
            "name": name,
            "healthy": healthy,
            "status_code": response.status_code,
            "url_checked": url_checked,
            "response_ms": elapsed_ms,
        }
    except httpx.TimeoutException:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        store.update_check(name, False)
        return {
            "name": name,
            "healthy": False,
            "status_code": None,
            "url_checked": url_checked,
            "response_ms": elapsed_ms,
            "error": "timeout",
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        store.update_check(name, False)
        return {
            "name": name,
            "healthy": False,
            "status_code": None,
            "url_checked": url_checked,
            "response_ms": elapsed_ms,
            "error": str(exc),
        }


def check_all_health(store: ServiceStore, *, timeout: float = 3.0) -> dict[str, Any]:
    """Verifica saúde de todos os serviços com health_path definido."""
    rows = store.list_all()
    total_checked = 0
    healthy_count = 0
    unhealthy_count = 0
    skipped_count = 0
    results: list[dict[str, Any]] = []

    for row in rows:
        health_path = row.get("health_path")
        if not health_path:
            skipped_count += 1
            continue

        name = row["name"]
        result = check_health(store, name=name, timeout=timeout)
        total_checked += 1
        is_healthy = result.get("healthy", False)

        if is_healthy:
            healthy_count += 1
            # Se estava unknown ou stopped, marcar como running
            current_status = row.get("status", "unknown")
            if current_status in ("unknown", "stopped"):
                store.upsert(name, {"status": "running"})
        else:
            unhealthy_count += 1
            # Se estava running, marcar como stopped
            current_status = row.get("status", "unknown")
            if current_status == "running":
                store.upsert(name, {"status": "stopped"})

        results.append(result)

    return {
        "total_checked": total_checked,
        "healthy": healthy_count,
        "unhealthy": unhealthy_count,
        "skipped": skipped_count,
        "results": results,
    }
