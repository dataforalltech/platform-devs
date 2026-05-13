from __future__ import annotations

from typing import Any, Literal

ServiceType = Literal[
    "docker", "process", "remote", "unknown",
    "mysql", "mariadb", "postgres", "redis", "kafka", "mongodb",
]
ServiceStatus = Literal["running", "stopped", "unknown"]
EnvironmentName = Literal["local", "dev", "hml", "prod"]


def service_record(row: dict) -> dict[str, Any]:
    """Converte row do banco em dict serializavel."""
    import json

    return {
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "url": row.get("url"),
        "internal_url": row.get("internal_url"),
        "type": row["type"],
        "container_name": row.get("container_name"),
        "pid": row.get("pid"),
        "status": row["status"],
        "health_path": row.get("health_path"),
        "environment": row["environment"],
        "tags": json.loads(row.get("tags") or "[]"),
        "metadata": json.loads(row.get("metadata") or "{}"),
        # Runtime environment
        "runtime": row.get("runtime") or "unknown",
        "deploy_mode": row.get("deploy_mode") or "unknown",
        "os_name": row.get("os_name"),
        "os_release": row.get("os_release"),
        "hostname": row.get("hostname"),
        # Timestamps
        "registered_at": row.get("registered_at"),
        "last_seen": row.get("last_seen"),
        "last_check_at": row.get("last_check_at"),
        "last_check_ok": bool(row["last_check_ok"]) if row.get("last_check_ok") is not None else None,
    }
