"""Tools de Deployment — CRUD que persiste o registro de deploy fornecido pelo agente.

O cálculo puro `recommend_strategy` (ambiente → estratégia de rollout determinística)
é **dobrado** aqui: `save_deployment` o chama para preencher `strategy` quando o agente
não a fornece, e persiste o resultado. A função segue exposta como função pura
(`recommend_strategy`) para reuso/teste."""

from __future__ import annotations

from typing import Any

from ..db.store import DevopsStore

# Estratégia de rollout recomendada por ambiente (determinística). Prod é conservador
# (blue/green — troca atômica com rollback rápido); homolog usa rolling; dev recreate.
_STRATEGY_BY_ENV = {
    "prod": "blue_green",
    "production": "blue_green",
    "prd": "blue_green",
    "hml": "rolling",
    "homolog": "rolling",
    "staging": "rolling",
    "stg": "rolling",
    "dev": "recreate",
    "development": "recreate",
    "local": "recreate",
}
_DEFAULT_STRATEGY = "rolling"


def recommend_strategy(environment: str) -> str:
    """Cálculo puro: ambiente → estratégia de rollout. Determinístico (default rolling)."""
    return _STRATEGY_BY_ENV.get(environment.strip().lower(), _DEFAULT_STRATEGY)


async def save_deployment(
    store: DevopsStore,
    application: str,
    environment: str,
    version: str,
    strategy: str | None = None,
    notes: str | None = None,
    meta: Any = None,
    status: str = "pending",
) -> dict[str, Any]:
    """Persiste um deploy. Se `strategy` não vier, recomenda-a de forma determinística."""
    final_strategy = strategy or recommend_strategy(environment)
    deployment = await store.save_deployment(
        application=application,
        environment=environment,
        version=version,
        strategy=final_strategy,
        notes=notes,
        meta=meta,
        status=status,
    )
    return {"saved": True, "deployment": deployment, "recommended_strategy": final_strategy}


async def list_deployments(
    store: DevopsStore,
    application: str | None = None,
    environment: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    deployments = await store.list_deployments(
        application=application, environment=environment, status=status
    )
    return {
        "total": len(deployments),
        "filters": {"application": application, "environment": environment, "status": status},
        "deployments": deployments,
    }


async def get_deployment(store: DevopsStore, deployment_id: int) -> dict[str, Any]:
    deployment = await store.get_deployment(deployment_id)
    if deployment is None:
        return {"error": "not_found", "id": deployment_id}
    return deployment


async def update_deployment_status(store: DevopsStore, deployment_id: int, status: str) -> dict[str, Any]:
    deployment = await store.update_deployment_status(deployment_id, status)
    if deployment is None:
        return {"error": "not_found", "id": deployment_id}
    return {"updated": True, "deployment": deployment}


async def delete_deployment(store: DevopsStore, deployment_id: int) -> dict[str, Any]:
    deleted = await store.delete_deployment(deployment_id)
    return {"deleted": deleted > 0, "id": deployment_id, "deleted_count": deleted}
