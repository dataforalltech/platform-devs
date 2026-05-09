"""Tools para mapeamento de portas."""

from __future__ import annotations

from typing import Any

from ..db.store import ServiceStore
from ..models.service import service_record


def _validation_error(tool: str, details: str) -> dict[str, Any]:
    return {"error": "ValidationError", "tool": tool, "details": details}


def get_port_map(store: ServiceStore) -> dict[str, Any]:
    """Retorna mapa de porta → serviço para todos os serviços com porta definida."""
    rows = store.list_all()
    port_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        port = row.get("port")
        if port is not None:
            port_map[str(port)] = {
                "name": row["name"],
                "host": row["host"],
                "type": row["type"],
                "status": row["status"],
            }
    return {"total": len(port_map), "port_map": port_map}


def find_by_port(store: ServiceStore, *, port: int) -> dict[str, Any]:
    """Encontra serviço por porta."""
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return _validation_error(
            "find_by_port", f"port inválido: {port!r}. Deve ser inteiro entre 1 e 65535."
        )
    rows = store.list_all()
    for row in rows:
        if row.get("port") == port:
            return {"found": True, "port": port, "service": service_record(row)}
    return {"found": False, "port": port}
