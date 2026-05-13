"""Tool launch_service â€” sobe um serviÃ§o via uvicorn, docker ou docker-compose,
registra no registry e monitora com health check.

Modos suportados
----------------
- uvicorn      : spawna `uvicorn <app> --host <host> --port <port>` como subprocess
- docker       : executa `docker run -d --name <name> -p <port>:<container_port> <image>`
- docker-compose: executa `docker compose up -d <service>` no diretÃ³rio configurado

ApÃ³s o start
------------
1. Aguarda o serviÃ§o responder no health_path (polling com timeout)
2. Faz upsert no ServiceStore (type, port, url, internal_url, pid/container_id, status)
3. Retorna status detalhado: started, healthy, pid/container_id, url, tempo atÃ© ready
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import logging
from pathlib import Path
from typing import Any

import httpx

from ..db.store import ServiceStore

_log = logging.getLogger(__name__)

# â”€â”€ Constantes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DEFAULT_WAIT_TIMEOUT = 30      # segundos esperando o serviÃ§o responder
_DEFAULT_CHECK_INTERVAL = 1.0   # intervalo entre tentativas de health
_DEFAULT_HEALTH_TIMEOUT = 2.0   # timeout por requisiÃ§Ã£o HTTP de health


# â”€â”€ Entry point pÃºblico â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def launch_service(
    store: ServiceStore,
    *,
    name: str,
    mode: str,
    port: int,
    # uvicorn
    app: str | None = None,
    host: str = "localhost",
    cwd: str | None = None,
    extra_args: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
    # docker
    image: str | None = None,
    container_port: int | None = None,
    container_name: str | None = None,
    # docker-compose
    compose_file: str | None = None,
    compose_service: str | None = None,
    # registro
    health_path: str = "/v1/health",
    environment: str = "local",
    tags: list[str] | None = None,
    # controle
    wait_timeout: int = _DEFAULT_WAIT_TIMEOUT,
    detach: bool = True,
) -> dict[str, Any]:
    """Sobe um serviÃ§o e registra no registry.

    Modes:
    - 'uvicorn': spawna `uvicorn <app> --host <host> --port <port>` como processo filho.
      Requer `app` (ex: 'mypackage.main:app').
    - 'docker': executa `docker run -d -p <port>:<container_port> <image>`.
      Requer `image`.
    - 'docker-compose': executa `docker compose up -d <compose_service>`.
      Usa `compose_file` (default: docker-compose.yml no cwd) e `compose_service`.

    ApÃ³s o start aguarda atÃ© wait_timeout segundos pelo health_path responder,
    depois registra e retorna status detalhado.
    """
    mode = mode.lower().strip()
    if mode not in ("uvicorn", "docker", "docker-compose"):
        return {"error": "InvalidMode", "details": f"mode deve ser 'uvicorn', 'docker' ou 'docker-compose'. Recebido: {mode!r}"}

    if not name or not name.strip():
        return {"error": "ValidationError", "details": "name nÃ£o pode ser vazio"}
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return {"error": "ValidationError", "details": f"port invÃ¡lido: {port!r}"}

    # â”€â”€ Executa o start no modo correto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    if mode == "uvicorn":
        if not app:
            return {"error": "ValidationError", "details": "app Ã© obrigatÃ³rio para mode=uvicorn (ex: 'mypackage.main:app')"}
        start_result = _launch_uvicorn(
            name=name, app=app, host=host, port=port,
            cwd=cwd, extra_args=extra_args or [], env_vars=env_vars or {},
        )

    elif mode == "docker":
        if not image:
            return {"error": "ValidationError", "details": "image Ã© obrigatÃ³rio para mode=docker"}
        start_result = _launch_docker(
            name=container_name or name, image=image,
            host_port=port, container_port=container_port or port,
            env_vars=env_vars or {}, extra_args=extra_args or [],
        )

    else:  # docker-compose
        svc = compose_service or name
        start_result = _launch_compose(
            service=svc, compose_file=compose_file, cwd=cwd,
        )

    if "error" in start_result:
        return start_result

    # â”€â”€ Aguarda o serviÃ§o responder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    external_url = f"http://{host}:{port}"
    health_result = _wait_healthy(
        url=external_url,
        health_path=health_path,
        wait_timeout=wait_timeout,
        check_interval=_DEFAULT_CHECK_INTERVAL,
        http_timeout=_DEFAULT_HEALTH_TIMEOUT,
    )

    # â”€â”€ Registra no store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    svc_type = "process" if mode == "uvicorn" else "docker"
    internal_url = f"http://{container_name or name}:{container_port or port}" if mode in ("docker", "docker-compose") else None

    fields: dict[str, Any] = {
        "host": host,
        "port": port,
        "url": external_url,
        "type": svc_type,
        "status": "running" if health_result["healthy"] else "stopped",
        "health_path": health_path,
        "environment": environment,
        "tags": tags or [],
    }
    if internal_url:
        fields["internal_url"] = internal_url
    if mode == "uvicorn" and start_result.get("pid"):
        fields["pid"] = start_result["pid"]
    if mode in ("docker", "docker-compose") and start_result.get("container_id"):
        fields["container_name"] = container_name or name
        fields["metadata"] = json.dumps({
            "container_id": start_result["container_id"],
            "image": image or "",
        })

    store.upsert(name, fields)
    _log.info("launch_service name=%s mode=%s port=%d healthy=%s", name, mode, port, health_result["healthy"])

    return {
        "name": name,
        "mode": mode,
        "port": port,
        "external_url": external_url,
        "internal_url": internal_url,
        "status": fields["status"],
        "healthy": health_result["healthy"],
        "health_url": health_result["url_checked"],
        "ready_in_ms": health_result.get("ready_in_ms"),
        "attempts": health_result.get("attempts"),
        **{k: v for k, v in start_result.items() if k not in ("error",)},
        "registered": True,
    }


# â”€â”€ Helpers de start â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _launch_uvicorn(
    *,
    name: str,
    app: str,
    host: str,
    port: int,
    cwd: str | None,
    extra_args: list[str],
    env_vars: dict[str, str],
) -> dict[str, Any]:
    """Spawna uvicorn como processo filho (detached)."""
    cmd = [
        "uvicorn", app,
        "--host", host,
        "--port", str(port),
        "--log-level", "warning",
        *extra_args,
    ]

    env = os.environ.copy()
    env.update(env_vars)

    work_dir = Path(cwd).resolve() if cwd else None

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=work_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # No Windows: CREATE_NEW_PROCESS_GROUP para nÃ£o herdar SIGINT
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        _log.info("uvicorn spawned: name=%s pid=%d cmd=%s", name, proc.pid, " ".join(cmd))
        return {
            "started": True,
            "pid": proc.pid,
            "cmd": " ".join(cmd),
        }
    except FileNotFoundError:
        return {"error": "UvicornNotFound", "details": "uvicorn nÃ£o encontrado no PATH. Instale com: pip install uvicorn"}
    except Exception as exc:  # noqa: BLE001
        return {"error": "LaunchError", "details": str(exc)}


def _launch_docker(
    *,
    name: str,
    image: str,
    host_port: int,
    container_port: int,
    env_vars: dict[str, str],
    extra_args: list[str],
) -> dict[str, Any]:
    """Executa `docker run -d` e retorna o container_id."""
    cmd = ["docker", "run", "-d", "--name", name, f"-p{host_port}:{container_port}"]
    for k, v in env_vars.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += extra_args
    cmd.append(image)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return {"error": "DockerNotFound", "details": "docker nÃ£o encontrado no PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout", "details": "docker run demorou mais de 60s"}

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Container com mesmo nome jÃ¡ existe â†’ para e recria
        if "already in use" in stderr or "already exists" in stderr:
            _log.warning("container %s jÃ¡ existe â€” parando e recriando", name)
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return {"error": "DockerRunFailed", "details": result.stderr.strip()}
        else:
            return {"error": "DockerRunFailed", "details": stderr}

    container_id = result.stdout.strip()[:12]
    _log.info("docker run: name=%s container_id=%s image=%s", name, container_id, image)
    return {
        "started": True,
        "container_id": container_id,
        "image": image,
        "cmd": " ".join(cmd),
    }


def _launch_compose(
    *,
    service: str,
    compose_file: str | None,
    cwd: str | None,
) -> dict[str, Any]:
    """Executa `docker compose up -d <service>`."""
    cmd = ["docker", "compose"]
    if compose_file:
        cmd += ["-f", compose_file]
    cmd += ["up", "-d", service]

    work_dir = Path(cwd).resolve() if cwd else None

    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return {"error": "DockerNotFound", "details": "docker compose nÃ£o encontrado no PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout", "details": "docker compose up demorou mais de 120s"}

    if result.returncode != 0:
        return {"error": "ComposeUpFailed", "details": result.stderr.strip() or result.stdout.strip()}

    # Pega container_id do serviÃ§o que acabou de subir
    container_id = _get_compose_container_id(service, cwd=work_dir)
    _log.info("compose up: service=%s container_id=%s", service, container_id)
    return {
        "started": True,
        "container_id": container_id,
        "service": service,
        "cmd": " ".join(cmd),
        "output": result.stderr.strip()[-500:] if result.stderr.strip() else "",
    }


def _get_compose_container_id(service: str, cwd: Path | None) -> str | None:
    """Retorna o container_id do serviÃ§o docker-compose recÃ©m-subido."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", service],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()[:12] or None
    except Exception:  # noqa: BLE001
        return None


# â”€â”€ Health check com polling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _wait_healthy(
    *,
    url: str,
    health_path: str,
    wait_timeout: int,
    check_interval: float,
    http_timeout: float,
) -> dict[str, Any]:
    """Faz polling no health endpoint atÃ© responder ou estourar wait_timeout."""
    health_url = url.rstrip("/") + health_path
    deadline = time.monotonic() + wait_timeout
    attempts = 0
    start_ts = time.monotonic()

    while time.monotonic() < deadline:
        attempts += 1
        try:
            with httpx.Client(timeout=http_timeout) as client:
                r = client.get(health_url)
                if r.status_code < 500:
                    ready_ms = round((time.monotonic() - start_ts) * 1000)
                    return {
                        "healthy": True,
                        "url_checked": health_url,
                        "status_code": r.status_code,
                        "ready_in_ms": ready_ms,
                        "attempts": attempts,
                    }
        except Exception:  # noqa: BLE001
            pass  # ainda nÃ£o respondeu â€” tenta novamente

        time.sleep(check_interval)

    return {
        "healthy": False,
        "url_checked": health_url,
        "status_code": None,
        "ready_in_ms": round((time.monotonic() - start_ts) * 1000),
        "attempts": attempts,
        "error": f"timeout apÃ³s {wait_timeout}s ({attempts} tentativas)",
    }


# â”€â”€ stop_service (complementar) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def stop_service(
    store: ServiceStore,
    *,
    name: str,
    mode: str | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    """Para um serviÃ§o registrado.

    Detecta automaticamente o tipo se mode nÃ£o for informado:
    - docker: `docker stop <container_name>`
    - process (uvicorn): kill pelo PID registrado
    - docker-compose: `docker compose stop <service>`
    """
    row = store.get(name)
    if row is None:
        return {"error": "not_found", "name": name}

    svc_type = mode or row.get("type", "unknown")
    result: dict[str, Any] = {"name": name, "type": svc_type}

    if svc_type in ("docker", "docker-compose"):
        cname = row.get("container_name") or name
        try:
            r = subprocess.run(
                ["docker", "stop", "--time", str(timeout), cname],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            result["stopped"] = r.returncode == 0
            result["output"] = r.stdout.strip() or r.stderr.strip()
        except Exception as exc:  # noqa: BLE001
            result["stopped"] = False
            result["error"] = str(exc)

    elif svc_type == "process":
        pid = row.get("pid")
        if not pid:
            result["stopped"] = False
            result["error"] = "pid nÃ£o registrado para este serviÃ§o"
        else:
            try:
                import signal
                os.kill(int(pid), signal.SIGTERM)
                result["stopped"] = True
                result["pid"] = pid
            except ProcessLookupError:
                result["stopped"] = True
                result["note"] = "processo jÃ¡ nÃ£o existia"
            except Exception as exc:  # noqa: BLE001
                result["stopped"] = False
                result["error"] = str(exc)
    else:
        result["stopped"] = False
        result["error"] = f"tipo '{svc_type}' nÃ£o suportado para stop. Use mode='docker' ou mode='process'"

    if result.get("stopped"):
        store.upsert(name, {"status": "stopped"})

    return result
