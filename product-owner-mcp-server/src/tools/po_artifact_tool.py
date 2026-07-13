"""Tools de Artefato de PO — persiste o artefato estruturado gerado pelo agente.

Este é o "guarda-chuva" das antigas tools `generate_*`/`map_*` (jornada/riscos/
handoffs/discovery/gtm/release/feature_spec/métricas/análise de problema): em vez de
cuspir template fixo, o agente gera o `content` (o artefato estruturado) e
`save_po_artifact` o persiste como histórico append-only, classificado por `kind` e
`target`. Thin wrappers sobre o `ProductOwnerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ProductOwnerStore

VALID_KINDS = frozenset(
    {
        "journey",
        "risks",
        "handoff_architecture",
        "handoff_design",
        "handoff_engineering",
        "discovery",
        "gtm",
        "release",
        "feature_spec",
        "metrics",
        "problem",
    }
)


async def save_po_artifact(
    store: ProductOwnerStore,
    kind: str,
    target: str,
    content: Any = None,
    meta: Any = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    artifact = await store.save_artifact(kind=kind, target=target, content=content, meta=meta)
    return {"saved": True, "artifact": artifact}


async def list_po_artifacts(
    store: ProductOwnerStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {
        "total": len(artifacts),
        "filters": {"kind": kind, "target": target},
        "artifacts": artifacts,
    }


async def get_po_artifact(store: ProductOwnerStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_po_artifact(store: ProductOwnerStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
