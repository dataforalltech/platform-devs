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

from ..importer import ImportedDoc
from ..models import (
    GovDirectiveRow,
    GovDirectiveVersionRow,
    GovKindCapabilityRow,
    GovLcrDetailRow,
    GovLcrSubstitutionRow,
    GovStatusVocabRow,
)
from .schema import (
    DIRECTIVE_TABLE,
    DIRECTIVE_VERSION_TABLE,
    KIND_CAPABILITY_TABLE,
    LCR_DETAIL_TABLE,
    LCR_SUBSTITUTION_TABLE,
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
# "historico-substituido" existe no hub real (docs antigos que ficam como
# referência histórica de algo já substituído) além do "historico" simples —
# achado na importação do hub (ADR-018 Fase 1b), não estava no vocabulário
# original da Fase 1. "vigente" (visto em runbooks reais) é tratado como alias
# de "aceito" na camada de import (ver importer.IMPORT_STATUS_ALIASES), não
# precisa de entrada própria aqui.
#
# Os 4 códigos com applies_to_kind="lib_change_request" (Fase 1c) são o
# vocabulário PRÓPRIO do LCR (achado real: pendente-aprovacao/aprovado/
# implementado/bloqueado-dependencia-externa não têm sentido para uma
# diretriz normativa comum) — "substituido" já existe kind-agnóstico e é
# reaproveitado para o LCR (mesmo significado: foi substituído por outro).
STATUS_VOCAB: dict[str, tuple[str | None, bool]] = {
    "proposto": (None, False),
    "aceito": (None, False),
    "substituido": (None, True),
    "retirado": (None, True),
    "arquivado": (None, True),
    "deprecated": (None, True),
    "historico": (None, False),
    "historico-substituido": (None, True),
    "pendente-aprovacao": ("lib_change_request", False),
    "aprovado": ("lib_change_request", False),
    "implementado": ("lib_change_request", True),
    "bloqueado-dependencia-externa": ("lib_change_request", True),
}


class GuardianValidationError(ValueError):
    """Erro de validação de negócio (kind/status/uid) — mapeado a erro de tool."""


# Colunas TINYINT que o driver MySQL devolve como int (0/1) — normalizadas para bool
# real na saída da API (Postgres já devolve bool nativo, então isto é idempotente lá).
_BOOL_KEYS = frozenset(
    {"is_current", "allows_rfc2119", "allows_fileline", "is_terminal", "breaking"}
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
    """Store tenant-scoped: 6 repositórios ligados ao pool do tenant (fail-closed)."""

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
        self._lcr_details = session.repository(
            GovLcrDetailRow, table_name=LCR_DETAIL_TABLE
        )
        self._lcr_substitutions = session.repository(
            GovLcrSubstitutionRow, table_name=LCR_SUBSTITUTION_TABLE
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
        applies_to_kind, _ = STATUS_VOCAB[status]
        if applies_to_kind is not None and applies_to_kind != kind:
            raise GuardianValidationError(
                f"status {status!r} é exclusivo do kind {applies_to_kind!r}, "
                f"não de {kind!r}"
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
        directive = await self._directive_raw(directive_uid)
        if directive is None:
            raise GuardianValidationError(
                f"directive_uid não encontrado: {directive_uid!r}"
            )
        self._validate(directive["kind"], status)
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
        directive = await self._directive_raw(directive_uid)
        if directive is None:
            raise GuardianValidationError(
                f"directive_uid não encontrado: {directive_uid!r}"
            )
        self._validate(directive["kind"], status)
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

    # -- importação markdown→DB (ADR-018 Fase 1b) ------------------------------ #

    async def import_directive(self, doc: ImportedDoc) -> dict[str, Any]:
        """Importa um `importer.ImportedDoc` já parseado — idempotente: cria se
        novo, versiona (append-only) se o conteúdo mudou, no-op se está igual.

        `kind`/`directive_scope` são fixados na criação e NÃO são versionáveis
        aqui — se um reimport trouxer kind/scope diferentes do cabeçalho já
        persistido, isso é sinalizado em `kind_scope_mismatch` (não aplicado
        silenciosamente; provável erro de reorganização do hub que merece
        revisão humana, não um "corrigir e seguir" automático).

        Fase 1c: quando `doc.kind == "lib_change_request"`, os metadados de
        gestão de mudança (`lcr_detail`) e as arestas `substituido_por` são
        persistidos independente de a diretriz ser nova ou já existir — são
        upserts por chave natural, sem versionamento (não fazem parte do
        núcleo append-only)."""
        existing = await self._directive_raw(doc.directive_uid)
        if existing is None:
            created = await self.create_directive(
                directive_uid=doc.directive_uid,
                kind=doc.kind,
                title=doc.title,
                scope=doc.scope,
                status=doc.status,
                body_context=doc.body_context,
                body_decision=doc.body_decision,
                author_ref="hub-import",
            )
            await self._sync_lcr_extras(doc)
            return {
                "directive_uid": doc.directive_uid,
                "action": "created",
                "directive": created,
            }

        mismatch = (
            existing["kind"] != doc.kind or existing["directive_scope"] != doc.scope
        )
        current = await self._current_version(doc.directive_uid)
        unchanged = (
            current is not None
            and current["status"] == doc.status
            and (current["body_context"] or None) == (doc.body_context or None)
            and (current["body_decision"] or None) == (doc.body_decision or None)
            and (existing["title"] or None) == (doc.title or None)
        )
        if unchanged:
            await self._sync_lcr_extras(doc)
            return {
                "directive_uid": doc.directive_uid,
                "action": "unchanged",
                "kind_scope_mismatch": mismatch,
            }

        if existing["title"] != doc.title:
            await self._directives.update_where(
                {"directive_uid": doc.directive_uid},
                {"title": doc.title},
                user_id=_SYSTEM_USER,
            )
        updated = await self.update_directive(
            directive_uid=doc.directive_uid,
            status=doc.status,
            body_context=doc.body_context,
            body_decision=doc.body_decision,
            change_reason="reimport do hub markdown",
            author_ref="hub-import",
        )
        await self._sync_lcr_extras(doc)
        return {
            "directive_uid": doc.directive_uid,
            "action": "updated",
            "directive": updated,
            "kind_scope_mismatch": mismatch,
        }

    async def _sync_lcr_extras(self, doc: ImportedDoc) -> None:
        if doc.kind != "lib_change_request":
            return
        if doc.lcr_detail is not None:
            await self.set_lcr_detail(directive_uid=doc.directive_uid, **doc.lcr_detail)
        for target_ref in doc.lcr_substituted_by:
            await self.add_lcr_substitution(
                lcr_directive_uid=doc.directive_uid, target_ref=target_ref
            )

    async def diff_hub(self, imported_uids: set[str]) -> list[dict[str, Any]]:
        """Diretivas de escopo 'platform' persistidas que NÃO aparecem no
        conjunto importado desta rodada — candidatas a órfã/retirada do hub."""
        res = await self._directives.find(where={"directive_scope": "platform"})
        return [
            _jsonable(d) for d in res.rows() if d["directive_uid"] not in imported_uids
        ]

    # -- Library Change Request: metadados de gestão de mudança (Fase 1c) ------- #

    async def set_lcr_detail(
        self,
        *,
        directive_uid: str,
        biblioteca: str | None = None,
        repositorio: str | None = None,
        versao_atual: str | None = None,
        versao_alvo: str | None = None,
        tipo: str | None = None,
        breaking: bool = False,
        urgencia: str | None = None,
        aprovador: str | None = None,
        solicitante: str | None = None,
        achado: str | None = None,
        data_solicitacao: str | None = None,
    ) -> dict[str, Any]:
        """Upsert por `directive_uid` (chave natural) — relação 1:1 com uma
        diretriz de `kind='lib_change_request'`, sem versionamento."""
        await self._lcr_details.upsert(
            {
                "directive_uid": directive_uid,
                "biblioteca": biblioteca,
                "repositorio": repositorio,
                "versao_atual": versao_atual,
                "versao_alvo": versao_alvo,
                "tipo": tipo,
                "breaking": breaking,
                "urgencia": urgencia,
                "aprovador": aprovador,
                "solicitante": solicitante,
                "achado": achado,
                "data_solicitacao": data_solicitacao,
            },
            ["directive_uid"],
            user_id=_SYSTEM_USER,
        )
        return await self.get_lcr_detail(directive_uid) or {}

    async def get_lcr_detail(self, directive_uid: str) -> dict[str, Any] | None:
        res = await self._lcr_details.find(
            where={"directive_uid": directive_uid}, limit=1
        )
        rows = res.rows()
        return _jsonable(rows[0]) if rows else None

    async def add_lcr_substitution(
        self, *, lcr_directive_uid: str, target_ref: str
    ) -> None:
        """Idempotente por `(lcr_directive_uid, target_ref)` — reimportar o
        mesmo LCR não duplica a aresta."""
        await self._lcr_substitutions.upsert(
            {"lcr_directive_uid": lcr_directive_uid, "target_ref": target_ref},
            ["lcr_directive_uid", "target_ref"],
            user_id=_SYSTEM_USER,
        )

    async def list_lcr_substitutions(self, lcr_directive_uid: str) -> list[str]:
        res = await self._lcr_substitutions.find(
            where={"lcr_directive_uid": lcr_directive_uid},
            order_by=[Sort(column="target_ref")],
        )
        return [row["target_ref"] for row in res.rows()]
