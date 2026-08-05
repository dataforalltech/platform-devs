# Portado de `deploy-mcp-server/tests/test_ledger_tool_unit.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Testes unitários dos wrappers read-only do ledger histórico."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.domains.deploy.tools.ledger_tool import (
    get_deployment,
    list_deploy_events,
    list_deployments,
    list_pr_history,
    list_registered_repos,
    list_workflow_history,
)


@pytest.mark.asyncio
async def test_ledger_query_wrappers_preserve_filters_and_counts():
    store = AsyncMock()
    store.list_deployments.return_value = [{"id": 1}]
    store.list_events.return_value = [{"id": 2}]
    store.list_pull_requests.return_value = [{"number": 3}]
    store.list_workflow_runs.return_value = [{"run_id": "legacy"}]
    store.list_repos.return_value = [{"repo": "service"}]

    deployments = await list_deployments(store, "svc", "dev", "ok")
    events = await list_deploy_events(store, "commit", "svc")
    prs = await list_pr_history(store, "svc", "merged")
    workflows = await list_workflow_history(store, "svc", "completed")
    repos = await list_registered_repos(store)

    assert deployments["total"] == events["total"] == prs["total"] == 1
    assert workflows["workflow_runs"][0]["run_id"] == "legacy"
    assert repos == {"total": 1, "repos": [{"repo": "service"}]}
    store.list_deployments.assert_awaited_once_with(
        service="svc", environment="dev", status="ok"
    )


@pytest.mark.asyncio
async def test_get_deployment_returns_row_or_not_found():
    store = AsyncMock()
    store.get_deployment.side_effect = [{"id": 7}, None]
    assert await get_deployment(store, 7) == {"id": 7}
    assert await get_deployment(store, 8) == {"error": "not_found", "id": 8}
