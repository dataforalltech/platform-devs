"""Tools de Artefato de arquitetura — persiste o texto/código gerado pelo agente.

Guarda-chuva genérico para os artefatos que o agente produz (diagramas Mermaid/
PlantUML, ADRs, notas de decisão, markdown): em vez de template fixo, o agente gera o
`content` e `save_artifact` o persiste como histórico append-only, classificado por
`kind` e `target`. Thin wrappers sobre o `ArchitectureStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ArchitectureStore

VALID_KINDS = frozenset(
    {
        "adr",
        "c4",
        "diagram",
        "blueprint",
        "proposal",
        "decision",
        "mermaid",
        "plantuml",
        "markdown",
        "note",
    }
)


async def save_artifact(
    store: ArchitectureStore,
    kind: str,
    target: str,
    content: str,
    format: str | None = None,
    meta: Any = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    artifact = await store.save_artifact(kind=kind, target=target, content=content, format=format, meta=meta)
    return {"saved": True, "artifact": artifact}


async def list_artifacts(
    store: ArchitectureStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {"total": len(artifacts), "filters": {"kind": kind, "target": target}, "artifacts": artifacts}


async def get_artifact(store: ArchitectureStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_artifact(store: ArchitectureStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
