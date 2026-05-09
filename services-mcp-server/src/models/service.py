from __future__ import annotations

from typing import Any, Literal

ServiceType = Literal["docker", "process", "remote", "unknown"]
ServiceStatus = Literal["running", "stopped", "unknown"]
EnvironmentName = Literal["local", "dev", "hml", "prod"]


def service_record(row: dict) -> dict[str, Any]:
    """Converte row do SQLite em dict serializável."""
    import json

    return {
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "url": row["url"],
        "type": row["type"],
        "container_name": row["container_name"],
        "pid": row["pid"],
        "status": row["status"],
        "health_path": row["health_path"],
        "environment": row["environment"],
        "tags": json.loads(row["tags"] or "[]"),
        "metadata": json.loads(row["metadata"] or "{}"),
        "registered_at": row["registered_at"],
        "last_seen": row["last_seen"],
        "last_check_at": row["last_check_at"],
        "last_check_ok": bool(row["last_check_ok"]) if row["last_check_ok"] is not None else None,
    }
