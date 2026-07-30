"""Store do pipeline-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru para o **Repository** de alto nível + Query IR, ligado ao
pool **do tenant** (resolvido credencial-zero via `for_tenant`/`get_pool_for_tenant`,
ORM-H-12). Roda dual-db: o mesmo código serve MySQL (banco-por-tenant) e PostgreSQL
(schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update_where`/
`upsert`/`delete_where`). As 3 operações que "não encaixam" no CRUD trivial resolvem
canonicamente:
  * register por chave natural `service`  -> find_one + insert/update_where (preserva
    a semântica: no update só troca repo/base_branch, não reseta env/gates);
  * gate por (service, env, gate_type)     -> `upsert(conflict_columns=[...])`
    (ON DUPLICATE KEY no MySQL / ON CONFLICT no PG);
  * overview (contagens por env)           -> agregação em Python sobre `find().rows()`
    (dado minúsculo; evita GROUP BY e mantém orm-lint --strict limpo).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`) — os atores de negócio (promoted_by/
blocked_by/evaluated_by) continuam sendo strings em colunas próprias.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import GateRow, PipelineRow, PromotionRow
from .schema import GATES_TABLE, PIPELINES_TABLE, PROMOTIONS_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O ator de negócio real viaja em colunas próprias (promoted_by, blocked_by, ...).
_SYSTEM_USER = 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


DEFAULT_GATES: dict[str, list[str]] = {
    "dev": ["audit_compliance"],
    "homol": ["qa_tests", "pr_approved", "audit_compliance"],
    "prod": [
        "qa_tests",
        "security_scan",
        "pr_approved",
        "health_check",
        "audit_compliance",
    ],
}

VALID_ENVS = {"dev", "homol", "prod", "blocked", "rollback"}
VALID_GATE_TYPES = {
    "qa_tests",
    "security_scan",
    "pr_approved",
    "health_check",
    "manual_approval",
    "audit_compliance",
}


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Converte datetimes das colunas padrão (create_on/timestamp_refresh) em ISO str,
    para o `json.dumps` do envelope MCP não quebrar."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def _shape_pipeline(row: dict[str, Any]) -> dict[str, Any]:
    """Forma canônica da linha de pipeline: datetimes -> ISO, gates_config JSON -> dict."""
    shaped = _jsonable(row)
    gates_config = shaped.get("gates_config")
    if isinstance(gates_config, str):
        try:
            shaped["gates_config"] = json.loads(gates_config)
        except (json.JSONDecodeError, TypeError):
            shaped["gates_config"] = {}
    return shaped


class PipelineStore:
    """Store tenant-scoped: 3 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._pipelines = session.repository(PipelineRow, table_name=PIPELINES_TABLE)
        self._promotions = session.repository(PromotionRow, table_name=PROMOTIONS_TABLE)
        self._gates = session.repository(GateRow, table_name=GATES_TABLE)

    # -- helpers de leitura (dict cru, forma back-compat) ---------------------- #

    async def _pipeline_row(self, service: str) -> dict[str, Any] | None:
        res = await self._pipelines.find(where={"service": service}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _promotion_row(self, promotion_id: int) -> dict[str, Any] | None:
        res = await self._promotions.find(where={"id": promotion_id}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _gate_row(
        self, service: str, env: str, gate_type: str
    ) -> dict[str, Any] | None:
        res = await self._gates.find(
            where={"service": service, "env": env, "gate_type": gate_type}, limit=1
        )
        rows = res.rows()
        return rows[0] if rows else None

    # -- Pipelines ------------------------------------------------------------- #

    async def register_pipeline(
        self, service: str, repo: str, base_branch: str = "develop"
    ) -> dict:
        now = _now()
        existing = await self._pipeline_row(service)
        if existing is None:
            await self._pipelines.insert(
                {
                    "service": service,
                    "repo": repo,
                    "base_branch": base_branch,
                    "current_env": "dev",
                    "blocked": 0,
                    "gates_config": json.dumps(DEFAULT_GATES),
                    "registered_at": now,
                    "updated_at": now,
                },
                user_id=_SYSTEM_USER,
            )
            action = "created"
        else:
            # Semântica preservada: no re-register só atualiza repo/base_branch —
            # current_env/blocked/gates_config permanecem intactos.
            await self._pipelines.update_where(
                {"service": service},
                {"repo": repo, "base_branch": base_branch, "updated_at": now},
                user_id=_SYSTEM_USER,
            )
            action = "updated"
        row = await self._pipeline_row(service)
        return {"action": action, "pipeline": _shape_pipeline(row) if row else {}}

    async def get_pipeline(self, service: str) -> dict | None:
        row = await self._pipeline_row(service)
        if row is None:
            return None
        pipeline = _shape_pipeline(row)
        promos = await self._promotions.find(
            where={"service": service},
            order_by=[Sort(column="created_at", direction=SortDirection.DESC)],
            limit=10,
        )
        pipeline["recent_promotions"] = [_jsonable(p) for p in promos.rows()]
        return pipeline

    async def list_pipelines(
        self, env: str | None = None, status: str | None = None
    ) -> list[dict]:
        where: dict[str, Any] = {}
        if env:
            where["current_env"] = env
        if status == "blocked":
            where["blocked"] = 1
        elif status == "active":
            where["blocked"] = 0
        res = await self._pipelines.find(
            where=where or None,
            order_by=[Sort(column="service", direction=SortDirection.ASC)],
        )
        return [_shape_pipeline(r) for r in res.rows()]

    async def update_pipeline_env(
        self, service: str, env: str, version: str | None = None
    ) -> None:
        await self._pipelines.update_where(
            {"service": service},
            {"current_env": env, "current_version": version, "updated_at": _now()},
            user_id=_SYSTEM_USER,
        )

    async def block_pipeline(self, service: str, reason: str, blocked_by: str) -> dict:
        now = _now()
        await self._pipelines.update_where(
            {"service": service},
            {
                "blocked": 1,
                "block_reason": reason,
                "blocked_by": blocked_by,
                "blocked_at": now,
                "updated_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        row = await self._pipeline_row(service)
        return _shape_pipeline(row) if row else {}

    async def set_gates_config(self, service: str, gates_required: dict) -> dict:
        await self._pipelines.update_where(
            {"service": service},
            {"gates_config": json.dumps(gates_required), "updated_at": _now()},
            user_id=_SYSTEM_USER,
        )
        row = await self._pipeline_row(service)
        return _shape_pipeline(row) if row else {}

    # -- Promotions ------------------------------------------------------------ #

    async def add_promotion(
        self,
        service: str,
        from_env: str,
        to_env: str,
        promoted_by: str,
        reason: str | None,
        gates_snapshot: dict,
        deploy_ref: str | None,
        status: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> int:
        res = await self._promotions.insert(
            {
                "service": service,
                "from_env": from_env,
                "to_env": to_env,
                "promoted_by": promoted_by,
                "reason": reason,
                "gates_snapshot": json.dumps(gates_snapshot),
                "deploy_ref": deploy_ref,
                "pr_number": pr_number,
                "pr_url": pr_url,
                "status": status,
                "created_at": _now(),
            },
            user_id=_SYSTEM_USER,
        )
        return int(res.returned_id) if res.returned_id is not None else 0

    async def complete_promotion(self, promotion_id: int, status: str) -> None:
        await self._promotions.update(
            promotion_id,
            {"status": status, "completed_at": _now()},
            user_id=_SYSTEM_USER,
        )

    async def approve_promotion(
        self, promotion_id: int, approved_by: str
    ) -> dict | None:
        now = _now()
        await self._promotions.update(
            promotion_id,
            {
                "approved_by": approved_by,
                "approved_at": now,
                "status": "pending_external_execution",
            },
            user_id=_SYSTEM_USER,
        )
        row = await self._promotion_row(promotion_id)
        return _jsonable(row) if row else None

    async def get_promotion(self, promotion_id: int) -> dict | None:
        row = await self._promotion_row(promotion_id)
        return _jsonable(row) if row else None

    async def get_promotion_history(
        self, service: str | None = None, limit: int = 20
    ) -> list[dict]:
        res = await self._promotions.find(
            where={"service": service} if service else None,
            order_by=[Sort(column="created_at", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_jsonable(r) for r in res.rows()]

    # -- Gates ----------------------------------------------------------------- #

    async def upsert_gate(
        self,
        service: str,
        env: str,
        gate_type: str,
        passed: bool,
        details: str | None = None,
        evaluated_by: str | None = None,
    ) -> dict:
        await self._gates.upsert(
            {
                "service": service,
                "env": env,
                "gate_type": gate_type,
                "passed": 1 if passed else 0,
                "details": details,
                "evaluated_by": evaluated_by,
                "evaluated_at": _now(),
            },
            conflict_columns=["service", "env", "gate_type"],
            user_id=_SYSTEM_USER,
        )
        row = await self._gate_row(service, env, gate_type)
        return _jsonable(row) if row else {}

    async def get_gates(self, service: str, env: str) -> list[dict]:
        res = await self._gates.find(
            where={"service": service, "env": env},
            order_by=[Sort(column="gate_type", direction=SortDirection.ASC)],
        )
        return [_jsonable(r) for r in res.rows()]

    async def clear_gates(self, service: str, env: str) -> int:
        # Soft-delete canônico (excluded=1): as leituras filtram excluded=0, então os
        # gates "somem"; um novo add_gate_result reativa a linha via upsert.
        res = await self._gates.delete_where(
            {"service": service, "env": env}, user_id=_SYSTEM_USER
        )
        return res.rowcount

    async def get_pipeline_overview(self) -> dict:
        pipelines = (await self._pipelines.find()).rows()
        overview: dict[str, Any] = {}
        total = 0
        for pipeline in pipelines:
            env = pipeline["current_env"]
            total += 1
            bucket = overview.setdefault(env, {"total": 0, "blocked": 0, "active": 0})
            bucket["total"] += 1
            if pipeline.get("blocked"):
                bucket["blocked"] += 1
            else:
                bucket["active"] += 1

        failed_rows = (await self._gates.find(where={"passed": 0})).rows()
        failed_counts: dict[tuple[str, str], int] = {}
        for gate in failed_rows:
            key = (gate["service"], gate["env"])
            failed_counts[key] = failed_counts.get(key, 0) + 1

        return {
            "total_services": total,
            "by_env": overview,
            "services_with_failed_gates": [
                {"service": service, "env": env, "failed": count}
                for (service, env), count in failed_counts.items()
            ],
        }
