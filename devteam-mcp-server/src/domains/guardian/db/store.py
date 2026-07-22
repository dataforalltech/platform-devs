"""Store do domínio `guardian` — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped credencial-zero (`for_tenant`), dual-db. Fase 1 (ADR-018):
o núcleo versionado das diretrizes (`gov_directive` + `gov_directive_version`) e os
dados de referência (`gov_kind_capability`/`gov_status_vocab`).

Invariantes-chave (ADR-018):
- D18.3: identidade imutável por `directive_uid`; revisões append-only; "exatamente uma
  vigente por uid" via `Repository.transaction()` (UPDATE is_current=0 → INSERT is_current=1).
- D18.8: directive nunca soft-deletada; reimport = upsert por `directive_uid`.
- Enums (kind/status) validados app-level contra `KIND_CAPABILITIES`/`STATUS_VOCAB`
  (a matriz honesta do ADR — DB-CHECK/FK fica p/ refinamento).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import (
    GovDirectiveRow,
    GovDirectiveVersionRow,
    GovKindCapabilityRow,
    GovStatusVocabRow,
)
from .schema import (
    DIRECTIVE_TABLE,
    DIRECTIVE_VERSION_TABLE,
    KIND_CAPABILITY_TABLE,
    STATUS_VOCAB_TABLE,
)

_SYSTEM_USER = 0
_DESC = SortDirection.DESC

# Ranking do escopo hierárquico (ADR-018 D18.4): archetype=2 reservado (adicionado depois).
SCOPE_RANK: dict[str, int] = {"baseline": 0, "platform": 1, "project": 3}

# Capacidades por kind (ADR-018 D18 N1). (layer, allows_rfc2119, allows_fileline, body_shape)
KIND_CAPABILITIES: dict[str, tuple[int | None, bool, bool, str]] = {
    "principle": (1, False, False, "prose"),
    "adr": (2, True, False, "typed"),
    "platform_decision": (None, True, False, "typed"),
    "standard": (3, True, False, "typed"),
    "reference_arch": (4, False, True, "mixed"),
    "runbook": (5, False, False, "typed"),
    "work_instruction": (None, False, False, "typed"),
    "handoff": (None, False, False, "typed"),
    "decision": (None, False, False, "prose"),
    "spec": (None, False, False, "prose"),
    "lib_change_request": (None, False, False, "typed"),
    "adoption_contract_template": (None, False, False, "prose"),
}

# Vocabulário de status. (applies_to_kind, is_terminal)
STATUS_VOCAB: dict[str, tuple[str | None, bool]] = {
    "proposto": (None, False),
    "aceito": (None, False),
    "substituido": (None, True),
    "retirado": (None, True),
    "arquivado": (None, True),
    "deprecated": (None, True),
    "historico": (None, False),
}


class GuardianValidationError(ValueError):
    """Erro de validação de negócio (kind/status/uid) — mapeado a erro de tool."""


# Colunas TINYINT que o driver MySQL devolve como int (0/1) — normalizadas para bool
# real na saída da API (Postgres já devolve bool nativo, então isto é idempotente lá).
_BOOL_KEYS = frozenset(
    {"is_current", "allows_rfc2119", "allows_fileline", "is_terminal"}
)


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (
            v.isoformat()
            if isinstance(v, (datetime, date))
            else bool(v) if k in _BOOL_KEYS and v is not None else v
        )
        for k, v in row.items()
    }


def _content_sha256(
    uid: str, version: int, status: str, context: str | None, decision: str | None
) -> str:
    payload = json.dumps(
        {
            "uid": uid,
            "version": version,
            "status": status,
            "context": context,
            "decision": decision,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GuardianStore:
    """Store tenant-scoped: 4 repositórios ligados ao pool do tenant (fail-closed)."""

    def __init__(self, session: Any) -> None:
        self._directives = session.repository(
            GovDirectiveRow, table_name=DIRECTIVE_TABLE
        )
        self._versions = session.repository(
            GovDirectiveVersionRow, table_name=DIRECTIVE_VERSION_TABLE
        )
        self._kinds = session.repository(
            GovKindCapabilityRow, table_name=KIND_CAPABILITY_TABLE
        )
        self._status = session.repository(
            GovStatusVocabRow, table_name=STATUS_VOCAB_TABLE
        )

    # -- referência (seed idempotente + leitura) ------------------------------- #

    async def seed_reference_data(self) -> dict[str, int]:
        """Semeia (upsert idempotente por chave natural) as capacidades de kind e o
        vocabulário de status. Chamado no provisionamento do tenant."""
        for kind, (layer, rfc, fileline, shape) in KIND_CAPABILITIES.items():
            await self._kinds.upsert(
                {
                    "kind": kind,
                    "layer": layer,
                    "allows_rfc2119": rfc,
                    "allows_fileline": fileline,
                    "body_shape": shape,
                },
                ["kind"],
                user_id=_SYSTEM_USER,
            )
        for code, (applies, terminal) in STATUS_VOCAB.items():
            await self._status.upsert(
                {"code": code, "applies_to_kind": applies, "is_terminal": terminal},
                ["code"],
                user_id=_SYSTEM_USER,
            )
        return {"kinds": len(KIND_CAPABILITIES), "status": len(STATUS_VOCAB)}

    async def list_kinds(self) -> list[dict[str, Any]]:
        return [
            _jsonable(r)
            for r in (await self._kinds.find(order_by=[Sort(column="kind")])).rows()
        ]

    async def list_status_vocab(self) -> list[dict[str, Any]]:
        return [
            _jsonable(r)
            for r in (await self._status.find(order_by=[Sort(column="code")])).rows()
        ]

    # -- helpers internos ------------------------------------------------------ #

    async def _directive_raw(self, uid: str) -> dict[str, Any] | None:
        res = await self._directives.find(where={"directive_uid": uid}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _current_version(self, uid: str) -> dict[str, Any] | None:
        res = await self._versions.find(
            where={"directive_uid": uid, "is_current": True}, limit=1
        )
        rows = res.rows()
        return rows[0] if rows else None

    async def _next_version(self, uid: str) -> int:
        res = await self._versions.find(
            where={"directive_uid": uid},
            order_by=[Sort(column="version", direction=_DESC)],
            limit=1,
        )
        rows = res.rows()
        return (rows[0]["version"] + 1) if rows else 1

    async def _shaped(self, uid: str) -> dict[str, Any] | None:
        directive = await self._directive_raw(uid)
        if directive is None:
            return None
        out = _jsonable(directive)
        version = await self._current_version(uid)
        out["current_version"] = _jsonable(version) if version else None
        return out

    @staticmethod
    def _validate(kind: str, status: str) -> None:
        if kind not in KIND_CAPABILITIES:
            raise GuardianValidationError(
                f"kind inválido: {kind!r} (∈ {sorted(KIND_CAPABILITIES)})"
            )
        if status not in STATUS_VOCAB:
            raise GuardianValidationError(
                f"status inválido: {status!r} (∈ {sorted(STATUS_VOCAB)})"
            )

    # -- CRUD de diretriz ------------------------------------------------------ #

    async def create_directive(
        self,
        *,
        directive_uid: str,
        kind: str,
        title: str,
        scope: str = "platform",
        project_ref: str | None = None,
        owner_ref: str | None = None,
        status: str = "proposto",
        body_context: str | None = None,
        body_decision: str | None = None,
        author_ref: str | None = None,
    ) -> dict[str, Any]:
        self._validate(kind, status)
        if scope not in SCOPE_RANK:
            raise GuardianValidationError(
                f"scope inválido: {scope!r} (∈ {sorted(SCOPE_RANK)})"
            )
        if (scope == "project") != (project_ref is not None):
            raise GuardianValidationError(
                "project_ref é obrigatório sse scope='project'"
            )
        if await self._directive_raw(directive_uid) is not None:
            raise GuardianValidationError(
                f"directive_uid já existe: {directive_uid!r} (use update_directive)"
            )

        await self._directives.insert(
            {
                "directive_uid": directive_uid,
                "kind": kind,
                "directive_scope": scope,
                "scope_rank": SCOPE_RANK[scope],
                "project_ref": project_ref,
                "title": title,
                "owner_ref": owner_ref,
            },
            user_id=_SYSTEM_USER,
        )
        await self._versions.insert(
            {
                "directive_uid": directive_uid,
                "version": 1,
                "status": status,
                "is_current": True,
                "body_context": body_context,
                "body_decision": body_decision,
                "author_ref": author_ref,
                "content_sha256": _content_sha256(
                    directive_uid, 1, status, body_context, body_decision
                ),
            },
            user_id=_SYSTEM_USER,
        )
        return await self._shaped(directive_uid) or {}

    async def get_directive(self, directive_uid: str) -> dict[str, Any] | None:
        return await self._shaped(directive_uid)

    async def list_directives(
        self,
        *,
        kind: str | None = None,
        scope: str | None = None,
        project_ref: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if kind:
            where["kind"] = kind
        if scope:
            where["directive_scope"] = scope
        if project_ref:
            where["project_ref"] = project_ref
        res = await self._directives.find(
            where=where or None,
            order_by=[Sort(column="directive_uid")],
            limit=max(1, min(limit, 200)),
        )
        out: list[dict[str, Any]] = []
        for directive in res.rows():
            shaped = _jsonable(directive)
            version = await self._current_version(directive["directive_uid"])
            shaped["current_status"] = version["status"] if version else None
            shaped["current_version_number"] = version["version"] if version else None
            if status and shaped["current_status"] != status:
                continue
            out.append(shaped)
        return out

    async def update_directive(
        self,
        *,
        directive_uid: str,
        status: str = "proposto",
        body_context: str | None = None,
        body_decision: str | None = None,
        change_reason: str | None = None,
        author_ref: str | None = None,
    ) -> dict[str, Any]:
        if status not in STATUS_VOCAB:
            raise GuardianValidationError(
                f"status inválido: {status!r} (∈ {sorted(STATUS_VOCAB)})"
            )
        directive = await self._directive_raw(directive_uid)
        if directive is None:
            raise GuardianValidationError(
                f"directive_uid não encontrado: {directive_uid!r}"
            )
        version = await self._next_version(directive_uid)
        # Invariante "uma vigente por uid" (D18.3): UPDATE→INSERT atômico.
        async with self._versions.transaction() as tx:
            await tx.update_where(
                {"directive_uid": directive_uid},
                {"is_current": False},
                user_id=_SYSTEM_USER,
            )
            await tx.insert(
                {
                    "directive_uid": directive_uid,
                    "version": version,
                    "status": status,
                    "is_current": True,
                    "body_context": body_context,
                    "body_decision": body_decision,
                    "change_reason": change_reason,
                    "author_ref": author_ref,
                    "content_sha256": _content_sha256(
                        directive_uid, version, status, body_context, body_decision
                    ),
                },
                user_id=_SYSTEM_USER,
                # UnitOfWork.fetch_one (usado dentro de transaction()) não emula
                # RETURNING no MySQL como o pool top-level faz — pedir o id de volta
                # aqui quebraria com syntax error; não precisamos do id mesmo.
                returning=None,
            )
        return await self._shaped(directive_uid) or {}

    async def set_directive_status(
        self, *, directive_uid: str, status: str
    ) -> dict[str, Any]:
        if status not in STATUS_VOCAB:
            raise GuardianValidationError(f"status inválido: {status!r}")
        current = await self._current_version(directive_uid)
        if current is None:
            raise GuardianValidationError(
                f"directive_uid não encontrado: {directive_uid!r}"
            )
        await self._versions.update_where(
            {"directive_uid": directive_uid, "is_current": True},
            {"status": status},
            user_id=_SYSTEM_USER,
        )
        return await self._shaped(directive_uid) or {}

    async def supersede_directive(
        self, *, directive_uid: str, superseded_by_uid: str
    ) -> dict[str, Any]:
        directive = await self._directive_raw(directive_uid)
        if directive is None:
            raise GuardianValidationError(
                f"directive_uid não encontrado: {directive_uid!r}"
            )
        await self._directives.update_where(
            {"directive_uid": directive_uid},
            {"superseded_by_uid": superseded_by_uid},
            user_id=_SYSTEM_USER,
        )
        await self._versions.update_where(
            {"directive_uid": directive_uid, "is_current": True},
            {"status": "substituido"},
            user_id=_SYSTEM_USER,
        )
        return await self._shaped(directive_uid) or {}
