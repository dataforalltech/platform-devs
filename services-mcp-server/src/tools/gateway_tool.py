"""Tools de gateway â€” MAPPING_GATEWAY e sync de registry no startup.

Problema que resolve
--------------------
Quando o services-mcp roda em Docker, a URL interna de um serviÃ§o Ã©
`http://nome-do-container:porta` (DNS interno da rede Docker).
Quando roda via uvicorn local (dev), Ã© `http://localhost:porta`.

Essa divergÃªncia quebra chamadas entre serviÃ§os se usarem sempre a URL
externa. O MAPPING_GATEWAY armazena **ambas** as URLs e detecta o contexto
automaticamente.

Tools
-----
- get_gateway_map       â€” retorna o MAPPING_GATEWAY atual do banco
- update_service_gateway â€” atualiza internal_url + url de um serviÃ§o especÃ­fico
- sync_registry          â€” scan completo (Docker + portas) no startup; sincroniza
                           banco e gateway. Chamada automaticamente no boot.
"""

from __future__ import annotations

import os
import json
import re
import subprocess
import logging
from pathlib import Path
from typing import Any

import httpx

from ..db.store import ServiceStore

_log = logging.getLogger(__name__)

# â”€â”€ Contexto de execuÃ§Ã£o â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _is_docker() -> bool:
    """Detecta se o processo estÃ¡ rodando dentro de um container Docker."""
    return Path("/.dockerenv").exists() or os.getenv("RUNNING_IN_DOCKER", "") == "1"


def _derive_internal_url(name: str, port: int | None, container_name: str | None = None) -> str | None:
    """Deriva a URL interna Docker a partir do nome do serviÃ§o/container.

    Dentro do Docker, o hostname do serviÃ§o Ã© o nome do container na rede.
    Ex: container 'platform-auth' na porta 8001 â†’ http://platform-auth:8001
    """
    if port is None:
        return None
    host = (container_name or name).lstrip("/")
    return f"http://{host}:{port}"


def _derive_external_url(host: str, port: int | None) -> str | None:
    if port is None:
        return None
    h = host if host and host not in ("0.0.0.0", "::") else "localhost"
    return f"http://{h}:{port}"


def _parse_first_host_port(ports_str: str) -> int | None:
    """Extrai a porta do host de um campo Ports do docker ps.
    Ex: '0.0.0.0:8080->80/tcp' â†’ 8080
    """
    if not ports_str:
        return None
    match = re.search(r":(\d+)->", ports_str)
    return int(match.group(1)) if match else None


def _parse_container_port(ports_str: str) -> int | None:
    """Extrai a porta do container de um campo Ports do docker ps.
    Ex: '0.0.0.0:8080->80/tcp' â†’ 80
    """
    if not ports_str:
        return None
    match = re.search(r"->(\d+)/", ports_str)
    return int(match.group(1)) if match else None


def _probe_url(url: str, timeout: float = 2.0) -> bool:
    """Testa se uma URL responde com HTTP < 500."""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
            return r.status_code < 500
    except Exception:
        return False


# â”€â”€ Tools pÃºblicas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_gateway_map(store: ServiceStore) -> dict[str, Any]:
    """Retorna o MAPPING_GATEWAY â€” mapa de serviÃ§os com URLs interna e externa.

    Para cada serviÃ§o registrado, retorna:
    - external_url: URL acessÃ­vel do host (localhost:porta)
    - internal_url: URL interna Docker (nome-container:porta)
    - context: 'docker' ou 'local' â€” indica qual URL usar para chamadas internas
    - status: Ãºltimo status conhecido

    Use este mapa para rotear chamadas entre serviÃ§os corretamente, evitando
    divergÃªncias entre ambientes Docker e uvicorn local.
    """
    rows = store.list_all()
    in_docker = _is_docker()
    gateway: dict[str, dict[str, Any]] = {}

    for row in rows:
        name = row["name"]
        port = row.get("port")
        host = row.get("host") or "localhost"
        internal_url = row.get("internal_url") or _derive_internal_url(
            name, port, row.get("container_name")
        )
        external_url = row.get("url") or _derive_external_url(host, port)

        active_url = internal_url if in_docker else external_url

        gateway[name] = {
            "external_url": external_url,
            "internal_url": internal_url,
            "active_url": active_url,
            "context": "docker" if in_docker else "local",
            "host": host,
            "port": port,
            "status": row.get("status", "unknown"),
            "type": row.get("type", "unknown"),
            "health_path": row.get("health_path"),
        }

    return {
        "context": "docker" if in_docker else "local",
        "total": len(gateway),
        "gateway": gateway,
    }


def update_service_gateway(
    store: ServiceStore,
    *,
    name: str,
    internal_url: str | None = None,
    external_url: str | None = None,
    host: str | None = None,
    port: int | None = None,
    probe: bool = True,
) -> dict[str, Any]:
    """Atualiza as URLs de gateway de um serviÃ§o no banco.

    Resolve a divergÃªncia Docker vs uvicorn:
    - Se internal_url nÃ£o fornecida, deriva automaticamente do nome do container
    - Se external_url nÃ£o fornecida, deriva de host:port
    - Com probe=True, testa as URLs antes de salvar e marca o status

    Use quando um serviÃ§o subir em um novo endereÃ§o (ex: mudanÃ§a de porta
    ou migraÃ§Ã£o Docker â†’ uvicorn) para manter o MAPPING_GATEWAY atualizado.
    """
    row = store.get(name)
    if row is None:
        return {"error": "not_found", "name": name}

    # Resolver valores: usa os fornecidos ou deriva dos existentes
    effective_port = port or row.get("port")
    effective_host = host or row.get("host") or "localhost"
    effective_internal = internal_url or _derive_internal_url(
        name, effective_port, row.get("container_name")
    )
    effective_external = external_url or _derive_external_url(effective_host, effective_port)

    # Probe (opcional) â€” verifica qual URL responde
    probe_results: dict[str, Any] = {}
    status = row.get("status", "unknown")
    if probe:
        if effective_external:
            probe_results["external"] = _probe_url(effective_external)
        if effective_internal and not _is_docker():
            # SÃ³ proba internal se nÃ£o estivermos dentro do Docker
            # (de dentro do Docker, internal sempre funciona via DNS)
            probe_results["internal"] = _probe_url(effective_internal)

        if probe_results.get("external") or probe_results.get("internal"):
            status = "running"
        elif probe_results:
            status = "stopped"

    fields: dict[str, Any] = {"status": status}
    if effective_internal:
        fields["internal_url"] = effective_internal
    if effective_external:
        fields["url"] = effective_external
    if effective_host:
        fields["host"] = effective_host
    if effective_port:
        fields["port"] = effective_port

    store.upsert(name, fields)

    return {
        "name": name,
        "internal_url": effective_internal,
        "external_url": effective_external,
        "status": status,
        "probe": probe_results,
        "context": "docker" if _is_docker() else "local",
    }


def sync_registry(
    store: ServiceStore,
    *,
    port_ranges: str | None = None,
    service_names: list[str] | None = None,
    include_docker: bool = True,
    probe_health: bool = True,
    docker_timeout: int = 10,
) -> dict[str, Any]:
    """Scan completo de descoberta â€” sincroniza banco e MAPPING_GATEWAY.

    Executado automaticamente no startup do services-mcp e disponÃ­vel como
    tool para re-sincronizaÃ§Ã£o manual.

    O que faz:
    1. Scan Docker (docker ps) â€” descobre containers ativos, porta host e
       porta interna; salva internal_url correta para cada um
    2. Scan de portas â€” proba portas nos ranges configurados procurando
       serviÃ§os HTTP ativos
    3. Scan por nomes â€” se service_names fornecidos, tenta resolver via
       Docker DNS (contexto Docker) ou localhost
    4. Upsert de tudo no banco com internal_url e external_url corretos

    Args:
        port_ranges: Ranges de porta para probar, ex: '8000-8100,27100-27130'.
                     Default: lÃª PORT_SCAN_RANGES do ambiente ou '8000-8100'.
        service_names: Lista de nomes de serviÃ§os para tentar descobrir via DNS.
                       Default: lÃª SERVICE_NAMES do ambiente (CSV).
        include_docker: Se True, roda scan_docker. Default: True.
        probe_health: Se True, proba /health em cada serviÃ§o encontrado.
        docker_timeout: Timeout para comando docker ps.
    """
    in_docker = _is_docker()
    results: dict[str, Any] = {
        "context": "docker" if in_docker else "local",
        "docker_scan": None,
        "port_scan": None,
        "name_scan": None,
        "total_upserted": 0,
        "gateway_updated": 0,
    }

    # â”€â”€ 1. Scan Docker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    docker_upserted = 0
    if include_docker:
        docker_result = _scan_docker_with_gateway(store, timeout=docker_timeout)
        results["docker_scan"] = docker_result
        docker_upserted = docker_result.get("upserted", 0)

    # â”€â”€ 2. Scan de portas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    raw_ranges = port_ranges or os.getenv("PORT_SCAN_RANGES", "8000-8100")
    port_result = _scan_port_ranges(store, raw_ranges, probe=probe_health)
    results["port_scan"] = port_result

    # â”€â”€ 3. Scan por nomes de serviÃ§os â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    names_env = os.getenv("SERVICE_NAMES", "")
    names_list = service_names or ([n.strip() for n in names_env.split(",") if n.strip()])
    if names_list:
        name_result = _scan_by_names(store, names_list, probe=probe_health)
        results["name_scan"] = name_result

    # â”€â”€ Totais â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ #
    results["total_upserted"] = (
        docker_upserted
        + port_result.get("found", 0)
        + (results["name_scan"] or {}).get("found", 0)
    )
    results["gateway_updated"] = results["total_upserted"]
    _log.info(
        "sync_registry complete context=%s upserted=%d",
        results["context"],
        results["total_upserted"],
    )
    return results


# â”€â”€ Helpers internos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _scan_docker_with_gateway(store: ServiceStore, *, timeout: int = 10) -> dict[str, Any]:
    """Scan docker ps salvando internal_url correta para cada container."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {"upserted": 0, "error": "docker not found"}
    except subprocess.TimeoutExpired:
        return {"upserted": 0, "error": f"docker ps timeout ({timeout}s)"}

    if result.returncode != 0:
        return {"upserted": 0, "error": result.stderr.strip()}

    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    upserted = 0
    containers = []

    for line in lines:
        try:
            cdata = json.loads(line)
        except json.JSONDecodeError:
            continue

        raw_name = cdata.get("Names", "")
        svc_name = raw_name.lstrip("/") or f"docker-{cdata.get('ID','')[:8]}"
        ports_str = cdata.get("Ports", "")

        # Porta do host (acesso externo)
        host_port = _parse_first_host_port(ports_str)
        # Porta do container (acesso interno via DNS)
        container_port = _parse_container_port(ports_str) or host_port

        external_url = _derive_external_url("localhost", host_port)
        internal_url = _derive_internal_url(svc_name, container_port, svc_name)

        fields: dict[str, Any] = {
            "type": "docker",
            "status": "running",
            "container_name": svc_name,
            "host": "localhost",
            "metadata": json.dumps({"image": cdata.get("Image", ""), "ports_raw": ports_str}),
        }
        if host_port:
            fields["port"] = host_port
        if external_url:
            fields["url"] = external_url
        if internal_url:
            fields["internal_url"] = internal_url

        store.upsert(svc_name, fields)
        upserted += 1
        containers.append({
            "name": svc_name,
            "host_port": host_port,
            "container_port": container_port,
            "external_url": external_url,
            "internal_url": internal_url,
        })

    return {"upserted": upserted, "containers": containers}


def _scan_port_ranges(
    store: ServiceStore,
    ranges_str: str,
    *,
    probe: bool = True,
    timeout: float = 1.5,
) -> dict[str, Any]:
    """Proba portas em ranges buscando serviÃ§os HTTP."""
    ports_to_scan: list[int] = []
    for part in ranges_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                lo, hi = part.split("-", 1)
                ports_to_scan.extend(range(int(lo), int(hi) + 1))
            except ValueError:
                pass
        elif part.isdigit():
            ports_to_scan.append(int(part))

    found = []
    for port in ports_to_scan:
        url = f"http://localhost:{port}"
        if not probe or _probe_url(url, timeout=timeout):
            # Tenta identificar o serviÃ§o via /health ou /
            svc_name = _identify_service(port, timeout=timeout)
            if svc_name:
                external_url = url
                internal_url = _derive_internal_url(svc_name, port)
                store.upsert(svc_name, {
                    "host": "localhost",
                    "port": port,
                    "url": external_url,
                    "internal_url": internal_url,
                    "type": "process",
                    "status": "running",
                })
                found.append({"name": svc_name, "port": port, "url": url})

    return {"scanned": len(ports_to_scan), "found": len(found), "services": found}


def _identify_service(port: int, *, timeout: float = 1.5) -> str | None:
    """Tenta identificar o nome do serviÃ§o na porta via /health ou /."""
    for path in ("/health", "/v1/health", "/", "/api/health"):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"http://localhost:{port}{path}")
                if r.status_code < 500:
                    body = r.json() if "json" in r.headers.get("content-type", "") else {}
                    # Tenta extrair o nome do serviÃ§o da resposta
                    for key in ("server", "service", "name", "app"):
                        if key in body and isinstance(body[key], str):
                            return body[key].replace("_", "-").replace(" ", "-").lower()
                    # Fallback: nome genÃ©rico baseado na porta
                    return f"service-port-{port}"
        except Exception:
            continue
    return None


def _scan_by_names(
    store: ServiceStore,
    names: list[str],
    *,
    probe: bool = True,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Resolve serviÃ§os por nome â€” via DNS Docker interno ou localhost."""
    in_docker = _is_docker()
    found = []

    for name in names:
        row = store.get(name)
        port = row.get("port") if row else None

        # Tenta URL interna primeiro (Docker DNS) ou localhost
        candidate_urls = []
        if in_docker and port:
            candidate_urls.append((f"http://{name}:{port}", "internal"))
        if port:
            candidate_urls.append((f"http://localhost:{port}", "external"))

        for url, kind in candidate_urls:
            if not probe or _probe_url(url, timeout=timeout):
                internal_url = f"http://{name}:{port}" if port else None
                external_url = f"http://localhost:{port}" if port else None
                store.upsert(name, {
                    "internal_url": internal_url,
                    "url": external_url,
                    "status": "running",
                })
                found.append({"name": name, "url": url, "kind": kind})
                break

    return {"scanned": len(names), "found": len(found), "services": found}
