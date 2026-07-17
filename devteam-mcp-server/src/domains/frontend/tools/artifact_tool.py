"""Tools de Artefato de UI — persiste o código/scaffold de frontend gerado pelo agente.

Este é o "guarda-chuva" das antigas tools `generate_*` (react_component/nextjs_page/
form/storybook_story) e de qualquer outro scaffold de UI (hook/layout/context/style/
util/api_client): em vez de cuspir template fixo, o agente gera o `content` (o código)
e `save_artifact` o persiste como histórico append-only, classificado por `kind` e
`target`. Thin wrappers sobre o `FrontendStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import FrontendStore

VALID_KINDS = frozenset(
    {
        "react_component",
        "nextjs_page",
        "form",
        "storybook_story",
        "hook",
        "layout",
        "context",
        "style",
        "util",
        "api_client",
    }
)


async def save_artifact(
    store: FrontendStore,
    kind: str,
    target: str,
    content: str,
    framework: str | None = None,
    meta: Any = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    artifact = await store.save_artifact(
        kind=kind, target=target, content=content, framework=framework, meta=meta
    )
    return {"saved": True, "artifact": artifact}


async def list_artifacts(
    store: FrontendStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {
        "total": len(artifacts),
        "filters": {"kind": kind, "target": target},
        "artifacts": artifacts,
    }


async def get_artifact(store: FrontendStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_artifact(store: FrontendStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
