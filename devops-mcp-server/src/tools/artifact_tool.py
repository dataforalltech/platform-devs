"""Tools de Artefato IaC — persiste o arquivo de infra-as-code gerado pelo agente.

Este é o "guarda-chuva" das antigas tools `generate_*` (dockerfile/github_actions/
helm_chart/k8s_manifest/...): em vez de cuspir template fixo, o agente gera o
`content` (o arquivo IaC) e `save_artifact` o persiste como histórico append-only,
classificado por `kind` e `target`. Thin wrappers sobre o `DevopsStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import DevopsStore

VALID_KINDS = frozenset(
    {
        "dockerfile",
        "github_actions",
        "gitlab_ci",
        "helm_chart",
        "k8s_manifest",
        "terraform",
        "compose",
        "ansible",
        "kustomize",
    }
)


async def save_artifact(
    store: DevopsStore,
    kind: str,
    target: str,
    content: str,
    tool: str | None = None,
    spec: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        return {"error": "invalid_kind", "kind": kind, "valid": sorted(VALID_KINDS)}
    artifact = await store.save_artifact(
        kind=kind, target=target, content=content, tool=tool, spec=spec, status=status
    )
    return {"saved": True, "artifact": artifact}


async def list_artifacts(
    store: DevopsStore, kind: str | None = None, target: str | None = None, limit: int = 50
) -> dict[str, Any]:
    artifacts = await store.list_artifacts(kind=kind, target=target, limit=limit)
    return {
        "total": len(artifacts),
        "filters": {"kind": kind, "target": target},
        "artifacts": artifacts,
    }


async def get_artifact(store: DevopsStore, artifact_id: int) -> dict[str, Any]:
    artifact = await store.get_artifact(artifact_id)
    if artifact is None:
        return {"error": "not_found", "id": artifact_id}
    return artifact


async def delete_artifact(store: DevopsStore, artifact_id: int) -> dict[str, Any]:
    deleted = await store.delete_artifact(artifact_id)
    return {"deleted": deleted > 0, "id": artifact_id, "deleted_count": deleted}
