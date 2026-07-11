"""Store do services-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru (pool global + `threading.Lock`) para o **Repository** de alto
nível, ligado ao pool **do tenant** (resolvido credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12). Roda dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update_where`/
`delete_where`). A superfície pública é preservada byte-a-byte para as 32 tools:
  * ``upsert(name, fields)``    -> find_one(live) + insert (create) / update_where (update
    parcial — só os campos informados). Preserva ``{"action": ..., "row": ...}``. Um `name`
    soft-deletado é reativado (excluded=0) em vez de gerar violação de UNIQUE.
  * ``get(name)``               -> find_one(live).
  * ``list_all(...)``           -> find(where=...) + filtro de tag em Python (JSON string).
  * ``delete(name)``            -> delete_where (soft-delete `excluded=1`).
  * ``update_check(name, ok)``  -> update_where (last_check_at / last_check_ok).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models.service import ServiceRow
from .schema import SERVICES_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
_SYSTEM_USER = 0

# Defaults históricos do schema SQLite-flavored (antes eram column DEFAULT; agora
# carimbados no path de criação, pois MySQL não aceita literal DEFAULT em coluna TEXT).
_CREATE_DEFAULTS: dict[str, Any] = {
    "host": "localhost",
    "type": "unknown",
    "status": "unknown",
    "health_path": "/health",
    "environment": "local",
    "tags": "[]",
    "metadata": "{}",
    "runtime": "unknown",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _serialize(fields: dict[str, Any]) -> dict[str, Any]:
    """Serializa tags (list) e metadata (dict) como string JSON (colunas TEXT)."""
    out = dict(fields)
    if isinstance(out.get("tags"), list):
        out["tags"] = json.dumps(out["tags"])
    if isinstance(out.get("metadata"), dict):
        out["metadata"] = json.dumps(out["metadata"])
    return out


class ServiceStore:
    """Store tenant-scoped: um repositório `services` ligado ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria o
    repositório canônico por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._services = session.repository(ServiceRow, table_name=SERVICES_TABLE)

    # -- helpers de leitura (dict cru) ----------------------------------------- #

    async def _live_row(self, name: str) -> dict[str, Any] | None:
        res = await self._services.find(where={"name": name}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _any_row(self, name: str) -> dict[str, Any] | None:
        res = await self._services.find(where={"name": name}, limit=1, include_soft_deleted=True)
        rows = res.rows()
        return rows[0] if rows else None

    # -- superfície pública ---------------------------------------------------- #

    async def upsert(self, name: str, fields: dict[str, Any]) -> dict[str, Any]:
        payload = _serialize(fields)
        existing = await self._live_row(name)
        if existing is not None:
            payload["last_seen"] = _now()
            await self._services.update_where({"name": name}, payload, user_id=_SYSTEM_USER)
            action = "updated"
        else:
            dead = await self._any_row(name)
            if dead is not None:
                # Reativa a linha soft-deletada (mesma chave única) em vez de re-inserir.
                payload["excluded"] = 0
                payload.setdefault("registered_at", _now())
                payload["last_seen"] = _now()
                await self._services.update_where(
                    {"name": name}, payload, user_id=_SYSTEM_USER, include_soft_deleted=True
                )
            else:
                for key, value in _CREATE_DEFAULTS.items():
                    payload.setdefault(key, value)
                payload["name"] = name
                payload.setdefault("registered_at", _now())
                await self._services.insert(payload, user_id=_SYSTEM_USER)
            action = "created"
        row = await self._any_row(name)
        return {"action": action, "row": row or {}}

    async def get(self, name: str) -> dict | None:
        return await self._live_row(name)

    async def list_all(
        self,
        environment: str | None = None,
        type_: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        runtime: str | None = None,
        deploy_mode: str | None = None,
    ) -> list[dict]:
        where: dict[str, Any] = {}
        if environment:
            where["environment"] = environment
        if type_:
            where["type"] = type_
        if status:
            where["status"] = status
        if runtime:
            where["runtime"] = runtime
        if deploy_mode:
            where["deploy_mode"] = deploy_mode
        res = await self._services.find(
            where=where or None, order_by=[Sort(column="name", direction=SortDirection.ASC)]
        )
        rows = res.rows()
        if tag:
            rows = [r for r in rows if tag in json.loads(r.get("tags") or "[]")]
        return rows

    async def delete(self, name: str) -> bool:
        # Soft-delete canônico (excluded=1): as leituras filtram excluded=0, então o
        # serviço "some"; um novo upsert reativa a linha via a mesma chave única.
        res = await self._services.delete_where({"name": name}, user_id=_SYSTEM_USER)
        return res.rowcount > 0

    async def update_check(self, name: str, ok: bool) -> None:
        await self._services.update_where(
            {"name": name},
            {"last_check_at": _now(), "last_check_ok": 1 if ok else 0},
            user_id=_SYSTEM_USER,
        )
