"""Tools de CONSULTA do ledger persistido (leem do banco do tenant, dual-db).

Estas tools NÃO tocam o GitHub/ACR — elas leem o histórico que as tools de ação
gravaram no ledger (deployments, eventos, PRs, workflow runs, repos registrados).
Thin wrappers async sobre o ``DeployStore`` (já ligado ao pool do tenant).
"""

from __future__ import annotations

from typing import Any

from ..db.store import DeployStore


async def list_deployments(
    store: DeployStore,
    service: str | None = None,
    environment: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    rows = await store.list_deployments(service=service, environment=environment, status=status)
    return {
        "total": len(rows),
        "filters": {"service": service, "environment": environment, "status": status},
        "deployments": rows,
    }


async def get_deployment(store: DeployStore, deployment_id: int) -> dict[str, Any]:
    row = await store.get_deployment(deployment_id)
    if row is None:
        return {"error": "not_found", "id": deployment_id}
    return row


async def list_deploy_events(
    store: DeployStore, kind: str | None = None, target: str | None = None
) -> dict[str, Any]:
    rows = await store.list_events(kind=kind, target=target)
    return {"total": len(rows), "filters": {"kind": kind, "target": target}, "events": rows}


async def list_pr_history(
    store: DeployStore, repo: str | None = None, state: str | None = None
) -> dict[str, Any]:
    rows = await store.list_pull_requests(repo=repo, state=state)
    return {"total": len(rows), "filters": {"repo": repo, "state": state}, "pull_requests": rows}


async def list_workflow_history(
    store: DeployStore, repo: str | None = None, status: str | None = None
) -> dict[str, Any]:
    rows = await store.list_workflow_runs(repo=repo, status=status)
    return {"total": len(rows), "filters": {"repo": repo, "status": status}, "workflow_runs": rows}


async def list_registered_repos(store: DeployStore) -> dict[str, Any]:
    rows = await store.list_repos()
    return {"total": len(rows), "repos": rows}
