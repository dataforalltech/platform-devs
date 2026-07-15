"""Tools de Contrato de API — upsert por chave natural composta (`endpoint`+`method`).

O agente gera o contrato (schemas de request/response, status codes); estas tools
persistem/atualizam o contrato do endpoint+verbo (upsert — re-chamar sobrescreve).
`save_api_contract` valida o método HTTP ANTES de tocar o store (guard determinístico).
Thin wrappers sobre o `BackendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import BackendStore

VALID_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def normalize_method(method: str) -> str:
    """Normaliza o verbo HTTP (uppercase/trim). Determinístico."""
    return method.strip().upper()


async def save_api_contract(
    store: BackendStore,
    endpoint: str,
    method: str,
    description: str | None = None,
    request_schema: Any = None,
    response_schema: Any = None,
    status_codes: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_method(method)
    if normalized not in VALID_METHODS:
        return {"error": "invalid_method", "method": method, "valid": sorted(VALID_METHODS)}
    contract = await store.save_api_contract(
        endpoint=endpoint,
        method=normalized,
        description=description,
        request_schema=request_schema,
        response_schema=response_schema,
        status_codes=status_codes,
        status=status,
    )
    return {"saved": True, "api_contract": contract}


async def list_api_contracts(
    store: BackendStore,
    endpoint: str | None = None,
    method: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    contracts = await store.list_api_contracts(endpoint=endpoint, method=method, status=status)
    return {
        "total": len(contracts),
        "filters": {"endpoint": endpoint, "method": method, "status": status},
        "api_contracts": contracts,
    }


async def get_api_contract(store: BackendStore, endpoint: str, method: str) -> dict[str, Any]:
    contract = await store.get_api_contract(endpoint, normalize_method(method))
    if contract is None:
        return {"error": "not_found", "endpoint": endpoint, "method": method}
    return contract


async def delete_api_contract(store: BackendStore, endpoint: str, method: str) -> dict[str, Any]:
    deleted = await store.delete_api_contract(endpoint, normalize_method(method))
    return {
        "deleted": deleted > 0,
        "endpoint": endpoint,
        "method": method,
        "deleted_count": deleted,
    }
