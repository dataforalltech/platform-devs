"""Tools de descoberta de serviços: docker, processos e health check."""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any

import httpx
import psutil

from ..db.store import ServiceStore


def _parse_first_port(ports_str: str) -> int | None:
    """Extrai a primeira porta do campo Ports do docker ps.

    Exemplo: '0.0.0.0:8080->80/tcp, :::8080->80/tcp' → 8080
    """
    if not ports_str:
        return None
    # Procura padrão host_port->container_port
    match = re.search(r":(\d+)->", ports_str)
    if match:
        return int(match.group(1))
    return None


def scan_docker(store: ServiceStore, *, timeout: int = 10) -> dict[str, Any]:
    """Executa `docker ps --format '{{json .}}'` e sincroniza registry.

    Cada linha do output é um objeto JSON descrevendo um container.
    Para cada container: upsert com type='docker', status='running'.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {
            "scanned": 0,
            "upserted": 0,
            "containers": [],
            "docker_error": "docker not installed or not in PATH",
        }
    except subprocess.TimeoutExpired:
        return {
            "scanned": 0,
            "upserted": 0,
            "containers": [],
            "docker_error": f"docker ps timed out after {timeout}s",
        }

    if result.returncode != 0:
        return {
            "scanned": 0,
            "upserted": 0,
            "containers": [],
            "docker_error": result.stderr.strip() or f"exit code {result.returncode}",
        }

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    containers: list[dict[str, Any]] = []
    upserted = 0

    for line in lines:
        try:
            cdata = json.loads(line)
        except json.JSONDecodeError:
            continue

        container_name = cdata.get("Names", "")
        ports_str = cdata.get("Ports", "")
        port = _parse_first_port(ports_str)
        image = cdata.get("Image", "")

        fields: dict[str, Any] = {
            "type": "docker",
            "status": "running",
            "container_name": container_name,
            "metadata": {"image": image, "ports_raw": ports_str},
        }
        if port is not None:
            fields["port"] = port

        svc_name = container_name.lstrip("/") if container_name else f"docker-{cdata.get('ID', '')[:8]}"

        # Ensure required fields for new records
        fields.setdefault("host", "localhost")

        store.upsert(svc_name, fields)
        upserted += 1

        containers.append(
            {
                "name": svc_name,
                "container_name": container_name,
                "port": port,
                "image": image,
                "ports_raw": ports_str,
            }
        )

    return {
        "scanned": len(lines),
        "upserted": upserted,
        "containers": containers,
        "docker_error": None,
    }


def scan_processes(store: ServiceStore, *, min_port: int = 1024) -> dict[str, Any]:
    """Usa psutil para listar processos em LISTEN com porta >= min_port."""
    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        return {"error": "permission_denied", "total": 0, "processes": []}

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

        processes.append(
            {
                "pid": pid,
                "name": proc_name,
                "port": port,
                "cmdline": cmdline,
                "status": "running",
            }
        )

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
