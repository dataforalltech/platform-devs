"""Tools compostas que combinam múltiplas operações."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from ..db.store import ServiceStore
from .discovery_tool import check_health
from .registry_tool import get_service


def service_status(store: ServiceStore, *, name: str, timeout: float = 3.0) -> dict[str, Any]:
    """Retorna dados do serviço + resultado do health check."""
    svc_result = get_service(store, name=name)
    if not svc_result.get("found"):
        return {
            "name": name,
            "found": False,
            "overall_status": "unknown",
        }

    health_result = check_health(store, name=name, timeout=timeout)
    healthy = health_result.get("healthy", False)
    error = health_result.get("error")

    if error == "not_found":
        overall_status = "unknown"
    elif healthy:
        overall_status = "healthy"
    else:
        overall_status = "unhealthy"

    return {
        "name": name,
        "found": True,
        "overall_status": overall_status,
        "service": svc_result["service"],
        "health": health_result,
    }


def reload_service(
    store: ServiceStore,
    *,
    name: str,
    wait_seconds: float = 3.0,
    health_timeout: float = 5.0,
) -> dict[str, Any]:
    """Recarrega um serviço registrado.

    Estratégia por tipo:
      docker  → docker restart <name>
      process → mata o processo pelo PID/porta (espera que o process manager reinicie)
      remote  → POST /<health_path_base>/reload ou /__reload
      unknown → apenas re-faz health check
    """
    svc_result = get_service(store, name=name)
    if not svc_result.get("found"):
        return {"error": "not_found", "name": name}

    svc = svc_result["service"]
    svc_type = svc.get("type", "unknown")
    port = svc.get("port")
    host = svc.get("host", "localhost")

    reload_method: str
    reload_output: str | None = None
    error: str | None = None

    # ── Docker ──────────────────────────────────────────────────────────────── #
    if svc_type == "docker":
        reload_method = "docker_restart"
        try:
            result = subprocess.run(
                ["docker", "restart", name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                reload_output = result.stdout.strip() or name
            else:
                error = result.stderr.strip() or f"docker restart retornou exit {result.returncode}"
        except FileNotFoundError:
            error = "Docker não encontrado no PATH."
        except subprocess.TimeoutExpired:
            error = "docker restart demorou mais de 30s."

    # ── Process ─────────────────────────────────────────────────────────────── #
    elif svc_type == "process":
        reload_method = "process_kill"
        try:
            import psutil  # noqa: PLC0415

            killed_pids: list[int] = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr.port == port and conn.status == "LISTEN":
                    try:
                        proc = psutil.Process(conn.pid)
                        proc.terminate()
                        killed_pids.append(conn.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            if killed_pids:
                reload_output = f"Processos terminados (PIDs: {killed_pids}). Aguarda reinício pelo process manager."
            else:
                error = f"Nenhum processo encontrado na porta {port}."
        except ImportError:
            error = "psutil não instalado — instale com: pip install psutil"

    # ── Remote ──────────────────────────────────────────────────────────────── #
    elif svc_type == "remote":
        reload_method = "http_reload"
        try:
            import urllib.request  # noqa: PLC0415

            base_url = svc.get("url") or f"http://{host}:{port}"
            for path in ["/reload", "/__reload", "/actuator/restart", "/api/reload"]:
                try:
                    req = urllib.request.Request(
                        f"{base_url}{path}",
                        method="POST",
                        headers={"Content-Type": "application/json"},
                        data=b"{}",
                    )
                    with urllib.request.urlopen(req, timeout=health_timeout) as resp:
                        reload_output = f"POST {path} → {resp.status}"
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not reload_output:
                error = "Nenhum endpoint de reload respondeu (tentei /reload, /__reload, /actuator/restart, /api/reload)."
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    # ── Unknown ─────────────────────────────────────────────────────────────── #
    else:
        reload_method = "health_recheck"
        reload_output = "Tipo 'unknown' — apenas re-verificando health."

    # ── Aguarda e faz health check ───────────────────────────────────────────── #
    if not error and wait_seconds > 0:
        time.sleep(wait_seconds)

    health = check_health(store, name=name, timeout=health_timeout)

    return {
        "name": name,
        "type": svc_type,
        "reload_method": reload_method,
        "reload_output": reload_output,
        "reload_error": error,
        "success": error is None,
        "health_after_reload": health,
    }


def list_environments(store: ServiceStore) -> dict[str, Any]:
    """Agrupa serviços por environment e conta totais."""
    rows = store.list_all()
    env_map: dict[str, dict[str, Any]] = {}

    for row in rows:
        env = row.get("environment") or "unknown"
        if env not in env_map:
            env_map[env] = {"environment": env, "total": 0, "running": 0, "stopped": 0, "unknown": 0}
        env_map[env]["total"] += 1
        status = row.get("status") or "unknown"
        if status == "running":
            env_map[env]["running"] += 1
        elif status == "stopped":
            env_map[env]["stopped"] += 1
        else:
            env_map[env]["unknown"] += 1

    environments = sorted(env_map.values(), key=lambda e: e["environment"])
    return {
        "total_services": len(rows),
        "total_environments": len(environments),
        "environments": environments,
    }
