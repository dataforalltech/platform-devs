"""Tools de Artefato de QA — persiste o código/cenário de teste gerado pelo agente.

Este é o "guarda-chuva" das antigas tools `generate_*` (e2e/api/unit/gherkin/
playwright/cypress/postman/k6/regression/smoke/uat/coverage/analysis/testability):
em vez de cuspir template fixo, o agente gera o `content` (o código/cenário) e
`save_artifact` o persiste como histórico append-only, classificado por `kind` e
`target`. Thin wrappers sobre o `QAEngineerStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import QAEngineerStore

VALID_KINDS = frozenset(
    {
        "e2e",
        "api",
        "unit",
        "gherkin",
        "playwright",
        "cypress",
        "postman",
        "k6",
        "regression",
        "smoke",
        "uat",
        "coverage",
        "analysis",
        "testability",
    }
)


async def save_artifact(
    store: QAEngineerStore,
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
    store: QAEngineerStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {
        "total": len(artifacts),
        "filters": {"kind": kind, "target": target},
        "artifacts": artifacts,
    }


async def get_artifact(store: QAEngineerStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_artifact(store: QAEngineerStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
