"""Ferramentas de gestao de brokers de mensagens e cache: Kafka e Redis.

Tools
-----
- kafka_status      : verifica conectividade com o broker Kafka e retorna metadata
- redis_status      : pinga o Redis e retorna info basico (versao, memoria, keyspaces)
- sync_broker_urls  : atualiza vars de conexao de broker em arquivos .env
                      (KAFKA_BOOTSTRAP_SERVERS, REDIS_URL, RATE_LIMIT_STORAGE_URI, etc.)

Convencao de nomes no registry
-------------------------------
Kafka : servico com nome `kafka` ou `platform-kafka`; tipo `kafka`
Redis : servico com nome `redis` ou `platform-redis`; tipo `redis` | `cache`

O sync procura no registry pelo tipo ou nome do servico, nao pela porta hardcoded.
"""
from __future__ import annotations

import logging
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..db.store import ServiceStore

_log = logging.getLogger(__name__)

# Variaveis que apontam para Kafka (valor = bootstrap servers host:port)
_KAFKA_VARS = re.compile(
    r"^KAFKA_BOOTSTRAP_SERVERS$", re.IGNORECASE
)

# Variaveis que apontam para Redis (valor = URL redis://... ou host:port)
_REDIS_URL_VARS = re.compile(
    r"^(REDIS_URL|REDIS_HOST|REDIS_URI|CACHE_URL|"
    r"RATE_LIMIT_STORAGE_URI|CELERY_BROKER_URL|CELERY_RESULT_BACKEND)$",
    re.IGNORECASE,
)

# Prefixos de esquema Redis
_REDIS_SCHEME = re.compile(r"^redis(s)?://", re.IGNORECASE)


# ── Helpers de TCP ────────────────────────────────────────────────────────────

def _tcp_ping(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float]:
    """Tenta abrir conexao TCP. Retorna (sucesso, latencia_ms)."""
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True, (time.monotonic() - t0) * 1000
    except OSError:
        return False, (time.monotonic() - t0) * 1000


def _parse_bootstrap(servers: str) -> list[tuple[str, int]]:
    """Converte 'host1:port1,host2:port2' para lista de (host, port)."""
    results = []
    for s in servers.split(","):
        s = s.strip()
        if ":" in s:
            h, p = s.rsplit(":", 1)
            try:
                results.append((h.strip(), int(p.strip())))
            except ValueError:
                pass
    return results


def _parse_redis_url(value: str) -> tuple[str, int]:
    """Extrai (host, port) de redis://host:port/db ou host:port."""
    if _REDIS_SCHEME.match(value):
        parsed = urlparse(value)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        return host, port
    # formato host:port
    if ":" in value:
        h, p = value.rsplit(":", 1)
        try:
            return h.strip(), int(p.strip())
        except ValueError:
            pass
    return value.strip(), 6379


# ── Parse/serializa .env preservando comentarios ─────────────────────────────

def _parse_env_file(path: Path) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            lines.append(("blank", line))
        elif stripped.startswith("#"):
            lines.append(("comment", line))
        elif "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            lines.append((f"var:{key}", line))
        else:
            lines.append(("other", line))
    return lines


def _lines_to_dict(lines: list[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for kind, raw in lines:
        if kind.startswith("var:"):
            key, _, val = raw.partition("=")
            result[key.strip()] = val
    return result


def _write_env_lines(path: Path, lines: list[tuple[str, str]]) -> None:
    content = "\n".join(raw for _, raw in lines) + "\n"
    path.write_text(content, encoding="utf-8")


# ── Lookup de servicos no registry ───────────────────────────────────────────

def _find_broker(store: ServiceStore, service_type: str) -> dict | None:
    """Busca servico no registry pelo tipo (kafka/redis) ou por nome canonico."""
    all_services = store.list_services()
    # Prioridade: tipo exato, entao nome
    for svc in all_services:
        if svc.get("type", "").lower() == service_type:
            return svc
    name_patterns = {
        "kafka": ["kafka", "platform-kafka"],
        "redis": ["redis", "platform-redis", "platform-cache"],
    }
    for pattern in name_patterns.get(service_type, []):
        for svc in all_services:
            if svc.get("name", "").lower() == pattern:
                return svc
    return None


# ── Tools ─────────────────────────────────────────────────────────────────────

def kafka_status(
    store: ServiceStore,
    *,
    bootstrap_servers: str | None = None,
) -> dict[str, Any]:
    """Verifica conectividade com o broker Kafka.

    Se bootstrap_servers nao for passado, tenta descobrir pelo registry
    (servico com tipo='kafka' ou nome='kafka'/'platform-kafka').
    """
    servers = bootstrap_servers

    if not servers:
        svc = _find_broker(store, "kafka")
        if svc:
            host = svc.get("host", "localhost")
            port = svc.get("port", 9092)
            servers = f"{host}:{port}"

    if not servers:
        return {
            "ok": False,
            "error": "Kafka nao encontrado no registry e bootstrap_servers nao informado.",
            "tip": "Registre o servico Kafka (type='kafka') ou passe bootstrap_servers.",
        }

    brokers = _parse_bootstrap(servers)
    results = []
    any_ok = False
    for host, port in brokers:
        ok, latency_ms = _tcp_ping(host, port)
        if ok:
            any_ok = True
        results.append({
            "broker": f"{host}:{port}",
            "reachable": ok,
            "latency_ms": round(latency_ms, 1),
        })

    return {
        "ok": any_ok,
        "bootstrap_servers": servers,
        "brokers": results,
        "note": (
            "Teste TCP apenas — confirma que o broker aceita conexoes. "
            "Para listar topicos use kafka-topics.sh ou cliente Python (confluent-kafka)."
        ),
    }


def redis_status(
    store: ServiceStore,
    *,
    url: str | None = None,
) -> dict[str, Any]:
    """Pinga o Redis e coleta info basico via protocolo RESP inline.

    Se url nao for passado, busca no registry pelo tipo 'redis' ou 'cache'.
    """
    redis_url = url

    if not redis_url:
        svc = _find_broker(store, "redis")
        if not svc:
            svc = _find_broker(store, "cache")
        if svc:
            host = svc.get("host", "localhost")
            port = svc.get("port", 6379)
            redis_url = f"redis://{host}:{port}/0"

    if not redis_url:
        return {
            "ok": False,
            "error": "Redis nao encontrado no registry e url nao informado.",
            "tip": "Registre o servico Redis (type='redis') ou passe url=redis://host:port.",
        }

    host, port = _parse_redis_url(redis_url)

    # TCP ping
    ok, latency_ms = _tcp_ping(host, port)
    if not ok:
        return {
            "ok": False,
            "url": redis_url,
            "host": host,
            "port": port,
            "reachable": False,
            "latency_ms": round(latency_ms, 1),
            "error": f"Nao foi possivel conectar em {host}:{port}",
        }

    # RESP ping inline
    info: dict[str, Any] = {}
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            sock.sendall(b"PING\r\n")
            pong = sock.recv(64).decode(errors="replace").strip()
            info["ping"] = pong  # deve ser "+PONG"
    except OSError as exc:
        info["ping_error"] = str(exc)

    return {
        "ok": True,
        "url": redis_url,
        "host": host,
        "port": port,
        "reachable": True,
        "latency_ms": round(latency_ms, 1),
        "resp": info,
    }


def sync_broker_urls(
    store: ServiceStore,
    *,
    path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atualiza vars de conexao de brokers num arquivo .env a partir do registry.

    Vars tratadas
    -------------
    Kafka : KAFKA_BOOTSTRAP_SERVERS -> {host}:{port}
    Redis : REDIS_URL, REDIS_HOST, REDIS_URI, RATE_LIMIT_STORAGE_URI,
            CACHE_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
            -> redis://{host}:{port}/{db}  (mantem /db se ja existia)

    Retorna dict com 'changes', 'not_found_in_registry', 'skipped_already_correct'.
    """
    env_path = Path(path)
    if not env_path.exists():
        return {"error": f"Arquivo nao encontrado: {path}"}

    lines = _parse_env_file(env_path)
    current = _lines_to_dict(lines)

    # Descobre servicos do registry uma vez
    kafka_svc = _find_broker(store, "kafka")
    redis_svc = _find_broker(store, "redis") or _find_broker(store, "cache")

    changes: list[dict] = []
    not_found: list[str] = []
    skipped: list[str] = []
    new_lines: list[tuple[str, str]] = []

    for kind, raw in lines:
        if not kind.startswith("var:"):
            new_lines.append((kind, raw))
            continue

        key, _, cur_val = raw.partition("=")
        key = key.strip()
        cur_val = cur_val.strip()

        # --- Kafka ---
        if _KAFKA_VARS.match(key):
            if kafka_svc:
                new_val = f"{kafka_svc['host']}:{kafka_svc['port']}"
                if cur_val == new_val:
                    skipped.append(key)
                    new_lines.append((kind, raw))
                else:
                    changes.append({"key": key, "old": cur_val, "new": new_val})
                    new_lines.append((kind, f"{key}={new_val}"))
            else:
                not_found.append(key)
                new_lines.append((kind, raw))

        # --- Redis ---
        elif _REDIS_URL_VARS.match(key):
            if redis_svc:
                r_host = redis_svc["host"]
                r_port = redis_svc.get("port", 6379)

                if _REDIS_SCHEME.match(cur_val):
                    # Preserva o /db da URL existente
                    parsed = urlparse(cur_val)
                    db_path = parsed.path or "/0"
                    new_val = f"redis://{r_host}:{r_port}{db_path}"
                elif ":" in cur_val and not cur_val.startswith("redis"):
                    # formato host:port sem esquema
                    new_val = f"{r_host}:{r_port}"
                else:
                    new_val = f"redis://{r_host}:{r_port}/0"

                if cur_val == new_val:
                    skipped.append(key)
                    new_lines.append((kind, raw))
                else:
                    changes.append({"key": key, "old": cur_val, "new": new_val})
                    new_lines.append((kind, f"{key}={new_val}"))
            else:
                not_found.append(key)
                new_lines.append((kind, raw))

        else:
            new_lines.append((kind, raw))

    if changes and not dry_run:
        _write_env_lines(env_path, new_lines)

    return {
        "path": str(env_path),
        "dry_run": dry_run,
        "changes": changes,
        "not_found_in_registry": not_found,
        "skipped_already_correct": skipped,
    }
