"""Tools de Artefato de Produto — persiste o documento/texto gerado pelo agente.

Este é o "guarda-chuva" das antigas tools `generate_*` (feature_spec/gtm/release/
vision) e de qualquer outro artefato de produto (roadmap/PRD/OKR/persona/user story/
discovery/analysis): em vez de cuspir template fixo, o agente gera o `content` (o
documento) e `save_artifact` o persiste como histórico append-only, classificado por
`kind` e `target`. Thin wrappers sobre o `ProductManagerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductManagerStore

VALID_KINDS = frozenset(
    {
        "product_vision",
        "feature_spec",
        "gtm_brief",
        "release_plan",
        "roadmap",
        "prd",
        "okr",
        "persona",
        "user_story",
        "discovery",
        "analysis",
    }
)


async def save_artifact(
    store: ProductManagerStore,
    kind: str,
    target: str,
    content: str,
    fmt: str | None = None,
    meta: Any = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    artifact = await store.save_artifact(kind=kind, target=target, content=content, fmt=fmt, meta=meta)
    return {"saved": True, "artifact": artifact}


async def list_artifacts(
    store: ProductManagerStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {
        "total": len(artifacts),
        "filters": {"kind": kind, "target": target},
        "artifacts": artifacts,
    }


async def get_artifact(store: ProductManagerStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_artifact(store: ProductManagerStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
