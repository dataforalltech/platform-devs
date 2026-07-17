"""Store do LEDGER do deploy-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via ``for_tenant`` /
``get_pool_for_tenant``, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "faz a ação, registra no ledger": as tools de ação continuam operando o
GitHub/ACR/git via o ``GitHubClient``; DEPOIS do sucesso, o servidor chama este store
para **persistir a operação**. Sem SQL manual: cada read/write cai no Repository
(``find``/``insert``/``update_where``/``upsert``/``delete_where``).

Chaves naturais (upsert, ON DUPLICATE KEY / ON CONFLICT):
  * pull_requests → (repo, number)
  * branches      → (repo, branch)
  * workflow_runs → (repo, run_id)
  * repos         → (repo)
Históricos append-only (chave surrogate ``id``): deployments, events.

Dados estruturados viajam como dict/list na API e são serializados em JSON (TEXT) na
persistência (dual-db safe). Convenções: ``PLATFORM_CONVENTIONS`` (soft-delete
``excluded=0``, auditoria ``id_user_*`` / ``timestamp_refresh``). Como
``id_user_created`` é NOT NULL sem default, todo write carimba o usuário-sistema.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from .models import (
    BranchRow,
    DeployEventRow,
    DeploymentRow,
    PullRequestRow,
    RepoRow,
    WorkflowRunRow,
)
from .schema import (
    BRANCHES_TABLE,
    DEPLOYMENTS_TABLE,
    EVENTS_TABLE,
    PULL_REQUESTS_TABLE,
    REPOS_TABLE,
    WORKFLOW_RUNS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O deploy-mcp não persiste um "ator" de negócio (o ledger é operacional/governança).
_SYSTEM_USER = 0

# Campos JSON serializados em TEXT, por tabela — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    DEPLOYMENTS_TABLE: ("detail",),
    PULL_REQUESTS_TABLE: (),
    BRANCHES_TABLE: (),
    WORKFLOW_RUNS_TABLE: ("detail",),
    REPOS_TABLE: ("config",),
    EVENTS_TABLE: ("detail",),
}


def _dumps(value: Any) -> str | None:
    """Serializa dict/list em JSON (TEXT). ``None`` permanece ``None`` (coluna NULL)."""
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _prune(record: dict[str, Any]) -> dict[str, Any]:
    """Payload de upsert com semântica de *merge*: descarta as chaves com valor ``None``.

    O ``upsert`` do ORM deriva o ``SET`` do ON DUPLICATE KEY UPDATE de TODAS as colunas
    não-chave presentes no payload. Se um campo omitido viajasse como ``None``, o
    update-path o sobrescreveria com ``NULL``, apagando o valor gravado numa chamada
    anterior (ex.: ``merge_pr`` só traz ``state='merged'`` e deve preservar título/base
    do ``create_pr`` anterior). Podando os ``None`` antes do upsert, só as colunas
    fornecidas entram no INSERT e no ``SET``. As chaves naturais são sempre não-``None``.
    """
    return {k: v for k, v in record.items() if v is not None}


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Datetimes das colunas padrão (create_on/timestamp_refresh) -> ISO str, para o
    ``json.dumps`` do envelope MCP não quebrar."""
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in row.items()}


def _shape(row: dict[str, Any], json_fields: tuple[str, ...]) -> dict[str, Any]:
    """Forma canônica de uma linha: datetimes -> ISO, campos JSON (TEXT) -> dict/list."""
    shaped = _jsonable(row)
    for field in json_fields:
        value = shaped.get(field)
        if isinstance(value, str):
            try:
                shaped[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                shaped[field] = None
    return shaped


class DeployStore:
    """Store tenant-scoped: 6 repositórios do ledger ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._deployments = session.repository(DeploymentRow, table_name=DEPLOYMENTS_TABLE)
        self._prs = session.repository(PullRequestRow, table_name=PULL_REQUESTS_TABLE)
        self._branches = session.repository(BranchRow, table_name=BRANCHES_TABLE)
        self._runs = session.repository(WorkflowRunRow, table_name=WORKFLOW_RUNS_TABLE)
        self._repos = session.repository(RepoRow, table_name=REPOS_TABLE)
        self._events = session.repository(DeployEventRow, table_name=EVENTS_TABLE)

    # -- helpers de leitura --------------------------------------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    @staticmethod
    async def _first(repo: Any, where: dict[str, Any], json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where=where, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Deployments (histórico append-only) ----------------------------------- #

    async def record_deployment(
        self,
        service: str,
        environment: str,
        status: str,
        ref: str | None = None,
        repo: str | None = None,
        workflow: str | None = None,
        run_id: str | None = None,
        detail: Any = None,
    ) -> dict[str, Any]:
        res = await self._deployments.insert(
            {
                "service": service,
                "environment": environment,
                "status": status,
                "ref": ref,
                "repo": repo,
                "workflow": workflow,
                "run_id": run_id,
                "detail": _dumps(detail),
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._deployments, new_id, _JSON_FIELDS[DEPLOYMENTS_TABLE])
        return row or {}

    async def list_deployments(
        self,
        service: str | None = None,
        environment: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if service:
            where["service"] = service
        if environment:
            where["environment"] = environment
        if status:
            where["status"] = status
        res = await self._deployments.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[DEPLOYMENTS_TABLE]) for r in res.rows()]

    async def get_deployment(self, deployment_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._deployments, deployment_id, _JSON_FIELDS[DEPLOYMENTS_TABLE])

    # -- Pull Requests (upsert por chave natural (repo, number)) --------------- #

    async def upsert_pull_request(
        self,
        repo: str,
        number: int,
        title: str | None = None,
        base: str | None = None,
        head: str | None = None,
        url: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        await self._prs.upsert(
            _prune(
                {
                    "repo": repo,
                    "number": number,
                    "title": title,
                    "base": base,
                    "head": head,
                    "url": url,
                    "state": state,
                }
            ),
            conflict_columns=["repo", "number"],
            user_id=_SYSTEM_USER,
        )
        row = await self._first(
            self._prs, {"repo": repo, "number": number}, _JSON_FIELDS[PULL_REQUESTS_TABLE]
        )
        return row or {}

    async def list_pull_requests(
        self, repo: str | None = None, state: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if repo:
            where["repo"] = repo
        if state:
            where["state"] = state
        res = await self._prs.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[PULL_REQUESTS_TABLE]) for r in res.rows()]

    # -- Branches (upsert por chave natural (repo, branch)) -------------------- #

    async def upsert_branch(
        self,
        repo: str,
        branch: str,
        from_ref: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._branches.upsert(
            _prune({"repo": repo, "branch": branch, "from_ref": from_ref, "status": status}),
            conflict_columns=["repo", "branch"],
            user_id=_SYSTEM_USER,
        )
        row = await self._first(
            self._branches, {"repo": repo, "branch": branch}, _JSON_FIELDS[BRANCHES_TABLE]
        )
        return row or {}

    async def list_branches(self, repo: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"repo": repo} if repo else {}
        res = await self._branches.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[BRANCHES_TABLE]) for r in res.rows()]

    # -- Workflow Runs (upsert por chave natural (repo, run_id)) --------------- #

    async def upsert_workflow_run(
        self,
        repo: str,
        run_id: str,
        workflow: str | None = None,
        status: str | None = None,
        conclusion: str | None = None,
        detail: Any = None,
    ) -> dict[str, Any]:
        await self._runs.upsert(
            _prune(
                {
                    "repo": repo,
                    "run_id": run_id,
                    "workflow": workflow,
                    "status": status,
                    "conclusion": conclusion,
                    "detail": _dumps(detail),
                }
            ),
            conflict_columns=["repo", "run_id"],
            user_id=_SYSTEM_USER,
        )
        row = await self._first(
            self._runs, {"repo": repo, "run_id": run_id}, _JSON_FIELDS[WORKFLOW_RUNS_TABLE]
        )
        return row or {}

    async def list_workflow_runs(
        self, repo: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if repo:
            where["repo"] = repo
        if status:
            where["status"] = status
        res = await self._runs.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[WORKFLOW_RUNS_TABLE]) for r in res.rows()]

    # -- Repos (upsert por chave natural única `repo`) ------------------------- #

    async def upsert_repo(self, repo: str, config: Any = None, status: str | None = None) -> dict[str, Any]:
        await self._repos.upsert(
            _prune({"repo": repo, "config": _dumps(config), "status": status}),
            conflict_columns=["repo"],
            user_id=_SYSTEM_USER,
        )
        row = await self._first(self._repos, {"repo": repo}, _JSON_FIELDS[REPOS_TABLE])
        return row or {}

    async def list_repos(self, limit: int = 100) -> list[dict[str, Any]]:
        res = await self._repos.find(
            order_by=[Sort(column="repo", direction=SortDirection.ASC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[REPOS_TABLE]) for r in res.rows()]

    # -- Events (histórico append-only genérico) ------------------------------- #

    async def record_event(
        self,
        kind: str,
        target: str | None = None,
        status: str | None = None,
        detail: Any = None,
    ) -> dict[str, Any]:
        res = await self._events.insert(
            {"kind": kind, "target": target, "status": status, "detail": _dumps(detail)},
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._events, new_id, _JSON_FIELDS[EVENTS_TABLE])
        return row or {}

    async def list_events(
        self, kind: str | None = None, target: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if kind:
            where["kind"] = kind
        if target:
            where["target"] = target
        res = await self._events.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[EVENTS_TABLE]) for r in res.rows()]
