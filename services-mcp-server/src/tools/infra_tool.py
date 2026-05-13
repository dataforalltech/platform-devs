"""Ferramentas de registro, mapeamento e sincronizacao de servicos de infraestrutura.

Servicos suportados: mysql, postgres, redis, kafka (e seus aliases mariadb, mongodb).

Tools
-----
- register_infra   : registra um servico de infra com defaults inteligentes por tipo
- scan_infra       : varre containers Docker e registra os de infra detectados pela imagem
- sync_infra_env   : atualiza vars de conexao de DB/Redis/Kafka num .env a partir do registry

Tipos e vars sincronizadas
--------------------------
mysql / mariadb  -> DB_HOST, DB_PORT, ADMIN_DB_HOST, ADMIN_DB_PORT
postgres         -> DB_HOST, DB_PORT, DATABASE_URL (reconstroi dsn)
redis / cache    -> REDIS_URL, REDIS_HOST, RATE_LIMIT_STORAGE_URI, CACHE_URL,
                    CELERY_BROKER_URL, CELERY_RESULT_BACKEND
kafka            -> KAFKA_BOOTSTRAP_SERVERS

Convencao de lookup no registry
---------------------------------
O sync busca por tipo exato primeiro, depois por nomes canonicos:
  mysql   : ["mysql", "platform-mysql", "mariadb", "db"]
  postgres: ["postgres", "postgresql", "platform-postgres", "db"]
  redis   : ["redis", "platform-redis", "platform-cache", "cache"]
  kafka   : ["kafka", "platform-kafka"]
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..db.store import ServiceStore

_log = logging.getLogger(__name__)

# ── Metadata por tipo de infra ────────────────────────────────────────────────

_INFRA_DEFAULTS: dict[str, dict] = {
    "mysql": {
        "port": 3306,
        "health_path": None,   # TCP-only, sem HTTP health
        "tags": ["infra", "database", "mysql"],
        "protocol": "mysql",
    },
    "mariadb": {
        "port": 3306,
        "health_path": None,
        "tags": ["infra", "database", "mysql", "mariadb"],
        "protocol": "mysql",
    },
    "postgres": {
        "port": 5432,
        "health_path": None,
        "tags": ["infra", "database", "postgres"],
        "protocol": "postgresql",
    },
    "postgresql": {
        "port": 5432,
        "health_path": None,
        "tags": ["infra", "database", "postgres"],
        "protocol": "postgresql",
    },
    "redis": {
        "port": 6379,
        "health_path": None,
        "tags": ["infra", "cache", "redis"],
        "protocol": "redis",
    },
    "kafka": {
        "port": 9092,       # porta interna Docker
        "host_port": 9094,  # porta EXTERNAL para acesso do host
        "health_path": None,
        "tags": ["infra", "messaging", "kafka"],
        "protocol": "kafka",
    },
    "mongodb": {
        "port": 27017,
        "health_path": None,
        "tags": ["infra", "database", "mongodb"],
        "protocol": "mongodb",
    },
}

# Imagens Docker -> tipo canonico
_IMAGE_TYPE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"mysql", re.IGNORECASE), "mysql"),
    (re.compile(r"mariadb", re.IGNORECASE), "mariadb"),
    (re.compile(r"postgres", re.IGNORECASE), "postgres"),
    (re.compile(r"redis", re.IGNORECASE), "redis"),
    (re.compile(r"kafka", re.IGNORECASE), "kafka"),
    (re.compile(r"mongo", re.IGNORECASE), "mongodb"),
    (re.compile(r"zookeeper", re.IGNORECASE), "zookeeper"),
]

# Nomes canonicos por tipo para lookup no registry
_CANONICAL_NAMES: dict[str, list[str]] = {
    "mysql":    ["mysql", "platform-mysql", "mariadb", "db"],
    "mariadb":  ["mariadb", "mysql", "platform-mysql", "db"],
    "postgres": ["postgres", "postgresql", "platform-postgres", "db"],
    "redis":    ["redis", "platform-redis", "platform-cache", "cache"],
    "kafka":    ["kafka", "platform-kafka"],
    "mongodb":  ["mongodb", "mongo", "platform-mongo"],
}

# Vars de .env por tipo
_DB_HOST_VARS = re.compile(r"^(DB_HOST|ADMIN_DB_HOST|ADMIN_DB_HOST_\w+)$", re.IGNORECASE)
_DB_PORT_VARS = re.compile(r"^(DB_PORT|ADMIN_DB_PORT|ADMIN_DB_PORT_\w+)$", re.IGNORECASE)
_REDIS_VARS   = re.compile(
    r"^(REDIS_URL|REDIS_HOST|REDIS_URI|RATE_LIMIT_STORAGE_URI|"
    r"CACHE_URL|CELERY_BROKER_URL|CELERY_RESULT_BACKEND)$",
    re.IGNORECASE,
)
_KAFKA_VARS   = re.compile(r"^KAFKA_BOOTSTRAP_SERVERS$", re.IGNORECASE)
_DB_ENGINE_VAR = re.compile(r"^DB_ENGINE$", re.IGNORECASE)
_DATABASE_URL  = re.compile(r"^DATABASE_URL$", re.IGNORECASE)
_REDIS_SCHEME  = re.compile(r"^redis(s)?://", re.IGNORECASE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_image_type(image: str) -> str | None:
    for pattern, kind in _IMAGE_TYPE_MAP:
        if pattern.search(image):
            return kind
    return None


def _parse_ports(ports_str: str) -> list[tuple[int, int]]:
    """Extrai lista de (host_port, container_port) do campo Ports do docker ps."""
    result = []
    for match in re.finditer(r":(\d+)->(\d+)", ports_str):
        result.append((int(match.group(1)), int(match.group(2))))
    return result


def _find_in_registry(store: ServiceStore, kind: str) -> dict | None:
    """Busca no registry: primeiro por type=kind, depois por nomes canonicos."""
    all_svcs = store.list_all()

    # Tipo exato (type exato no banco)
    for svc in all_svcs:
        if svc.get("type", "").lower() == kind:
            return svc
    # Alias (mariadb aceita registros mysql e vice-versa)
    aliases = {"mariadb": "mysql", "postgresql": "postgres"}
    alias = aliases.get(kind)
    if alias:
        for svc in all_svcs:
            if svc.get("type", "").lower() == alias:
                return svc

    # Nome canonico
    for canonical in _CANONICAL_NAMES.get(kind, []):
        for svc in all_svcs:
            if svc.get("name", "").lower() == canonical:
                return svc
    return None


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
            result[key.strip()] = val.strip()
    return result


def _write_env_lines(path: Path, lines: list[tuple[str, str]]) -> None:
    content = "\n".join(raw for _, raw in lines) + "\n"
    path.write_text(content, encoding="utf-8")


def _rebuild_redis_url(cur_val: str, new_host: str, new_port: int) -> str:
    """Substitui host:port numa URL Redis preservando esquema e /db."""
    if _REDIS_SCHEME.match(cur_val):
        parsed = urlparse(cur_val)
        scheme = parsed.scheme or "redis"
        db_path = parsed.path or "/0"
        return f"{scheme}://{new_host}:{new_port}{db_path}"
    if ":" in cur_val and not cur_val.startswith("redis"):
        return f"{new_host}:{new_port}"
    return f"redis://{new_host}:{new_port}/0"


# ── Tools ─────────────────────────────────────────────────────────────────────

def register_infra(
    store: ServiceStore,
    *,
    name: str,
    kind: str,
    host: str = "localhost",
    port: int | None = None,
    host_port: int | None = None,
    environment: str = "local",
    container_name: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Registra um servico de infraestrutura com defaults inteligentes por tipo.

    kind: mysql | postgres | redis | kafka | mongodb | mariadb
    host_port: porta mapeada no host (para Kafka com listener EXTERNAL).
    """
    kind_lower = kind.lower()
    defaults = _INFRA_DEFAULTS.get(kind_lower)
    if defaults is None:
        return {
            "error": f"Tipo desconhecido: {kind}. Use: {list(_INFRA_DEFAULTS.keys())}",
        }

    resolved_port = port or (host_port or defaults.get("host_port") or defaults["port"])

    fields: dict[str, Any] = {
        "type": kind_lower,
        "host": host,
        "port": resolved_port,
        "environment": environment,
        "tags": defaults["tags"],
        "status": "unknown",
        "metadata": {
            "protocol": defaults["protocol"],
            "default_port": defaults["port"],
            **({"host_port": host_port or defaults.get("host_port")} if kind_lower == "kafka" else {}),
            **(metadata or {}),
        },
    }

    # health_path: infra nao tem HTTP health; deixa null para nao confundir check_all_health
    if defaults["health_path"] is not None:
        fields["health_path"] = defaults["health_path"]

    if container_name:
        fields["container_name"] = container_name

    result = store.upsert(name, fields)
    return {
        "name": name,
        "kind": kind_lower,
        "host": host,
        "port": resolved_port,
        "action": result["action"],
        "defaults_applied": defaults,
    }


def scan_infra(
    store: ServiceStore,
    *,
    timeout: int = 10,
    environment: str = "local",
) -> dict[str, Any]:
    """Varre containers Docker e registra os de infraestrutura (mysql/postgres/redis/kafka).

    Detecta o tipo pelo nome da imagem.
    Para Kafka, usa a porta EXTERNAL (9094) se disponivel, senao a primeira mapeada.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {"scanned": 0, "registered": [], "error": "docker not found"}
    except subprocess.TimeoutExpired:
        return {"scanned": 0, "registered": [], "error": f"docker ps timeout ({timeout}s)"}

    if result.returncode != 0:
        return {
            "scanned": 0, "registered": [],
            "error": result.stderr.strip() or f"exit {result.returncode}",
        }

    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    registered: list[dict] = []
    skipped: list[str] = []

    for line in lines:
        try:
            cdata = json.loads(line)
        except json.JSONDecodeError:
            continue

        image = cdata.get("Image", "")
        kind = _detect_image_type(image)
        if kind is None:
            skipped.append(cdata.get("Names", image))
            continue

        container_name = cdata.get("Names", "").lstrip("/")
        ports_str = cdata.get("Ports", "")
        port_pairs = _parse_ports(ports_str)

        # Para Kafka: prefere porta 9094 (EXTERNAL), senao a primeira mapeada
        if kind == "kafka":
            kafka_port = next(
                (hp for hp, cp in port_pairs if cp == 9094 or hp == 9094),
                None,
            ) or next((hp for hp, _ in port_pairs), None) or 9094
            host_port = kafka_port
            port_used = kafka_port
        else:
            port_used = next((hp for hp, _ in port_pairs), _INFRA_DEFAULTS[kind]["port"])
            host_port = None

        # Nome canonico: usa o nome do container ou o tipo
        svc_name = container_name or kind

        reg = register_infra(
            store,
            name=svc_name,
            kind=kind,
            host="localhost",
            port=port_used,
            host_port=host_port,
            environment=environment,
            container_name=container_name,
            metadata={"image": image, "ports_raw": ports_str},
        )
        registered.append({
            "name": svc_name,
            "kind": kind,
            "port": port_used,
            "image": image,
            "action": reg.get("action"),
        })

    return {
        "scanned": len(lines),
        "registered": registered,
        "skipped_non_infra": skipped,
    }


def sync_infra_env(
    store: ServiceStore,
    *,
    path: str,
    dry_run: bool = False,
    db_kind: str | None = None,
) -> dict[str, Any]:
    """Atualiza todas as vars de conexao de infraestrutura num .env a partir do registry.

    Vars tratadas
    -------------
    DB: DB_HOST, DB_PORT, ADMIN_DB_HOST, ADMIN_DB_PORT
        Usa DB_ENGINE do proprio .env para saber se e mysql ou postgres.
        db_kind forca o tipo caso DB_ENGINE nao esteja no arquivo.

    Postgres: DATABASE_URL — reconstroi o DSN com o novo host/port.

    Redis: REDIS_URL, REDIS_HOST, REDIS_URI, RATE_LIMIT_STORAGE_URI,
           CACHE_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND.

    Kafka: KAFKA_BOOTSTRAP_SERVERS.
    """
    env_path = Path(path)
    if not env_path.exists():
        return {"error": f"Arquivo nao encontrado: {path}"}

    lines = _parse_env_file(env_path)
    current = _lines_to_dict(lines)

    # Determina tipo de DB
    raw_engine = current.get("DB_ENGINE", db_kind or "").lower()
    if "mysql" in raw_engine or "mariadb" in raw_engine:
        db_type = "mysql"
    elif "postgres" in raw_engine:
        db_type = "postgres"
    else:
        db_type = db_kind or "mysql"  # fallback

    # Busca servicos no registry
    db_svc    = _find_in_registry(store, db_type)
    redis_svc = _find_in_registry(store, "redis")
    kafka_svc = _find_in_registry(store, "kafka")

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
        cur_val_stripped = cur_val.strip()

        # --- DB_HOST / ADMIN_DB_HOST ---
        if _DB_HOST_VARS.match(key):
            if db_svc:
                new_val = db_svc["host"]
                if cur_val_stripped == new_val:
                    skipped.append(key)
                    new_lines.append((kind, raw))
                else:
                    changes.append({"key": key, "old": cur_val_stripped, "new": new_val})
                    new_lines.append((kind, f"{key}={new_val}"))
            else:
                not_found.append(key)
                new_lines.append((kind, raw))

        # --- DB_PORT / ADMIN_DB_PORT ---
        elif _DB_PORT_VARS.match(key):
            if db_svc and db_svc.get("port"):
                new_val = str(db_svc["port"])
                if cur_val_stripped == new_val:
                    skipped.append(key)
                    new_lines.append((kind, raw))
                else:
                    changes.append({"key": key, "old": cur_val_stripped, "new": new_val})
                    new_lines.append((kind, f"{key}={new_val}"))
            else:
                not_found.append(key) if not db_svc else skipped.append(key)
                new_lines.append((kind, raw))

        # --- DATABASE_URL (postgres DSN) ---
        elif _DATABASE_URL.match(key):
            if db_svc and db_type == "postgres":
                try:
                    parsed = urlparse(cur_val_stripped)
                    new_val = cur_val_stripped.replace(
                        f"{parsed.hostname}:{parsed.port or 5432}",
                        f"{db_svc['host']}:{db_svc.get('port', 5432)}",
                    )
                    if cur_val_stripped == new_val:
                        skipped.append(key)
                        new_lines.append((kind, raw))
                    else:
                        changes.append({"key": key, "old": cur_val_stripped, "new": new_val})
                        new_lines.append((kind, f"{key}={new_val}"))
                except Exception:
                    new_lines.append((kind, raw))
            else:
                if not db_svc:
                    not_found.append(key)
                new_lines.append((kind, raw))

        # --- Redis vars ---
        elif _REDIS_VARS.match(key):
            if redis_svc:
                r_host = redis_svc["host"]
                r_port = redis_svc.get("port", 6379)
                new_val = _rebuild_redis_url(cur_val_stripped, r_host, r_port)
                if cur_val_stripped == new_val:
                    skipped.append(key)
                    new_lines.append((kind, raw))
                else:
                    changes.append({"key": key, "old": cur_val_stripped, "new": new_val})
                    new_lines.append((kind, f"{key}={new_val}"))
            else:
                not_found.append(key)
                new_lines.append((kind, raw))

        # --- Kafka ---
        elif _KAFKA_VARS.match(key):
            if kafka_svc:
                # Usa host_port do metadata se disponivel (listener EXTERNAL)
                meta = kafka_svc.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                k_port = meta.get("host_port") or kafka_svc.get("port", 9094)
                k_host = kafka_svc["host"]
                new_val = f"{k_host}:{k_port}"
                if cur_val_stripped == new_val:
                    skipped.append(key)
                    new_lines.append((kind, raw))
                else:
                    changes.append({"key": key, "old": cur_val_stripped, "new": new_val})
                    new_lines.append((kind, f"{key}={new_val}"))
            else:
                not_found.append(key)
                new_lines.append((kind, raw))

        else:
            new_lines.append((kind, raw))

    if changes and not dry_run:
        _write_env_lines(env_path, new_lines)

    found_in_registry = {
        "db": {"name": db_svc["name"], "host": db_svc["host"], "port": db_svc.get("port")} if db_svc else None,
        "redis": {"name": redis_svc["name"], "host": redis_svc["host"], "port": redis_svc.get("port")} if redis_svc else None,
        "kafka": {"name": kafka_svc["name"], "host": kafka_svc["host"], "port": kafka_svc.get("port")} if kafka_svc else None,
    }

    return {
        "path": str(env_path),
        "dry_run": dry_run,
        "db_type_used": db_type,
        "found_in_registry": found_in_registry,
        "changes": changes,
        "not_found_in_registry": not_found,
        "skipped_already_correct": skipped,
    }
