"""Tools de Pipeline — CRUD que persiste a pipeline de CI/CD fornecida pelo agente.

O agente gera o conteúdo (stages/triggers/jobs); estas tools persistem no banco do
tenant e devolvem o registro com `id`. `provider` é validado contra um conjunto
conhecido (github_actions/gitlab_ci/...). Thin wrappers sobre o `DevopsStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import DevopsStore

VALID_PROVIDERS = frozenset({"github_actions", "gitlab_ci", "jenkins", "azure_pipelines", "circleci", "argo"})


async def save_pipeline(
    store: DevopsStore,
    application: str,
    provider: str,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    if provider not in VALID_PROVIDERS:
        return {"error": "invalid_provider", "provider": provider, "valid": sorted(VALID_PROVIDERS)}
    pipeline = await store.save_pipeline(
        application=application, provider=provider, content=content, status=status
    )
    return {"saved": True, "pipeline": pipeline}


async def list_pipelines(
    store: DevopsStore,
    application: str | None = None,
    provider: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    pipelines = await store.list_pipelines(application=application, provider=provider, status=status)
    return {
        "total": len(pipelines),
        "filters": {"application": application, "provider": provider, "status": status},
        "pipelines": pipelines,
    }


async def get_pipeline(store: DevopsStore, pipeline_id: int) -> dict[str, Any]:
    pipeline = await store.get_pipeline(pipeline_id)
    if pipeline is None:
        return {"error": "not_found", "id": pipeline_id}
    return pipeline


async def update_pipeline(
    store: DevopsStore,
    pipeline_id: int,
    provider: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    if provider is not None and provider not in VALID_PROVIDERS:
        return {"error": "invalid_provider", "provider": provider, "valid": sorted(VALID_PROVIDERS)}
    pipeline = await store.update_pipeline(pipeline_id, provider=provider, content=content, status=status)
    if pipeline is None:
        return {"error": "not_found", "id": pipeline_id}
    return {"updated": True, "pipeline": pipeline}


async def delete_pipeline(store: DevopsStore, pipeline_id: int) -> dict[str, Any]:
    deleted = await store.delete_pipeline(pipeline_id)
    return {"deleted": deleted > 0, "id": pipeline_id, "deleted_count": deleted}
