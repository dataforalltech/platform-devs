"""Tools CRUD para registro de serviços."""

from __future__ import annotations

from typing import Any

from ..db.store import ServiceStore
from ..models.service import service_record

VALID_TYPES = {"docker", "process", "remote", "unknown"}
VALID_ENVS = {"local", "dev", "hml", "prod"}
VALID_STATUSES = {"running", "stopped", "unknown"}


def _validation_error(tool: str, details: str) -> dict[str, Any]:
    return {"error": "ValidationError", "tool": tool, "details": details}


def register_service(
    store: ServiceStore,
    *,
    name: str,
    port: int,
    host: str = "localhost",
    url: str | None = None,
    health_path: str = "/health",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Registra ou atualiza um serviço no registry."""
    type_ = kwargs.get("type", "unknown")
    environment = kwargs.get("environment", "local")

    if not name or not name.strip():
        return _validation_error("register_service", "name não pode ser vazio.")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return _validation_error(
            "register_service", f"port inválido: {port!r}. Deve ser inteiro entre 1 e 65535."
        )
    if type_ not in VALID_TYPES:
        return _validation_error(
            "register_service",
            f"type inválido: {type_!r}. Use: {sorted(VALID_TYPES)}",
        )
    if environment not in VALID_ENVS:
        return _validation_error(
            "register_service",
            f"environment inválido: {environment!r}. Use: {sorted(VALID_ENVS)}",
        )

    fields: dict[str, Any] = {
        "host": host,
        "port": port,
        "url": url,
        "type": type_,
        "environment": environment,
        "health_path": health_path,
        "tags": tags or [],
        "metadata": metadata or {},
        "status": kwargs.get("status", "unknown"),
    }

    result = store.upsert(name, fields)
    return {
        "name": name,
        "action": result["action"],
        "service": service_record(result["row"]),
    }


def get_service(store: ServiceStore, *, name: str) -> dict[str, Any]:
    """Retorna os dados de um serviço pelo nome."""
    row = store.get(name)
    if row is None:
        return {"found": False, "name": name}
    return {"found": True, "service": service_record(row)}


def list_services(
    store: ServiceStore,
    *,
    environment: str | None = None,
    tag: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Lista serviços com filtros opcionais."""
    type_ = kwargs.get("type")
    status = kwargs.get("status")
    rows = store.list_all(environment=environment, type_=type_, status=status, tag=tag)
    return {"total": len(rows), "services": [service_record(r) for r in rows]}


def update_service(store: ServiceStore, *, name: str, **kwargs: Any) -> dict[str, Any]:
    """Atualiza campos de um serviço existente."""
    # Remove sentinels / None values and check that at least 1 field was given
    fields = {k: v for k, v in kwargs.items() if v is not None}

    if not fields:
        return _validation_error("update_service", "Pelo menos um campo deve ser informado.")

    # Validate individual fields when present
    if "port" in fields:
        port = fields["port"]
        if not isinstance(port, int) or not (1 <= port <= 65535):
            return _validation_error(
                "update_service",
                f"port inválido: {port!r}. Deve ser inteiro entre 1 e 65535.",
            )
    if "type" in fields and fields["type"] not in VALID_TYPES:
        return _validation_error(
            "update_service",
            f"type inválido: {fields['type']!r}. Use: {sorted(VALID_TYPES)}",
        )
    if "environment" in fields and fields["environment"] not in VALID_ENVS:
        return _validation_error(
            "update_service",
            f"environment inválido: {fields['environment']!r}. Use: {sorted(VALID_ENVS)}",
        )
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        return _validation_error(
            "update_service",
            f"status inválido: {fields['status']!r}. Use: {sorted(VALID_STATUSES)}",
        )

    existing = store.get(name)
    if existing is None:
        return {"error": "NotFound", "tool": "update_service", "name": name}

    result = store.upsert(name, fields)
    return {
        "name": name,
        "updated_fields": sorted(fields.keys()),
        "service": service_record(result["row"]),
    }


def unregister_service(store: ServiceStore, *, name: str) -> dict[str, Any]:
    """Remove um serviço do registry."""
    deleted = store.delete(name)
    return {"deleted": deleted, "name": name}
