"""Store do docs-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru para o **Repository** de alto nível + Query IR, ligado ao
pool **do tenant** (resolvido credencial-zero via `for_tenant`/`get_pool_for_tenant`,
ORM-H-12). Roda dual-db: o mesmo código serve MySQL (banco-por-tenant) e PostgreSQL
(schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`upsert`). A tabela
única sobrecarregada do legado (`documents` + discriminador `doc_type` + blob `content`)
foi desmembrada em DOIS repositórios limpos:
  * ``audits``    — histórico de auditoria (chave surrogate `id`); insert + find;
  * ``doc_index`` — índice de docs por (repo_path, file_path) -> `upsert`
    (ON DUPLICATE KEY no MySQL / ON CONFLICT no PG), substituindo o update-then-insert
    RACY do legado (que não tinha unique no banco).

Todos os campos antes enfiados no blob JSON `content` (score/grade/summary/details e
word_count/last_modified/content_hash/doc_title) são agora COLUNAS reais; os shapers
`_shape_audit`/`_shape_index` preservam EXATAMENTE a forma de retorno que as tools
consomem (back-compat).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`) — auditoria/scan não têm um usuário de
negócio.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import AuditRow, DocIndexRow
from .schema import AUDITS_TABLE, DOC_INDEX_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
_SYSTEM_USER = 0


def _now() -> str:
    """Retorna ISO timestamp com timezone."""
    return datetime.now(UTC).isoformat()


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Converte datetimes das colunas padrão (create_on/timestamp_refresh) em ISO str,
    para o `json.dumps` do envelope MCP não quebrar."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def _load_json(value: Any) -> Any:
    """Desserializa uma coluna JSON-TEXT; degrada p/ {} se ausente/inválida."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value if value is not None else {}


class DocsStore:
    """Store tenant-scoped: 2 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._audits = session.repository(AuditRow, table_name=AUDITS_TABLE)
        self._doc_index = session.repository(DocIndexRow, table_name=DOC_INDEX_TABLE)

    # -- shapers (forma back-compat que as tools consomem) --------------------- #

    def _shape_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        """Linha de `audits` -> forma do store legado (title derivado, JSON parseado)."""
        shaped = _jsonable(row)
        grade = shaped.get("grade")
        return {
            "id": shaped.get("id"),
            "repo_path": shaped.get("repo_path"),
            "title": f"Audit: {grade}",
            "score": shaped.get("score"),
            "grade": grade,
            "summary": _load_json(shaped.get("summary")),
            "details": _load_json(shaped.get("details")),
            "created_at": shaped.get("created_at"),
        }

    def _shape_index(self, row: dict[str, Any]) -> dict[str, Any]:
        """Linha de `doc_index` -> forma do store legado (title = doc_title)."""
        shaped = _jsonable(row)
        return {
            "id": shaped.get("id"),
            "repo_path": shaped.get("repo_path"),
            "doc_type": shaped.get("doc_type"),
            "title": shaped.get("doc_title"),
            "word_count": shaped.get("word_count") or 0,
            "last_modified": shaped.get("last_modified"),
            "content_hash": shaped.get("content_hash"),
            "file_path": shaped.get("file_path"),
            "created_at": shaped.get("created_at"),
        }

    # ── AUDIT OPERATIONS ─────────────────────────────────────────────────────── #

    async def save_audit(
        self,
        repo_path: str,
        score: int,
        grade: str,
        summary: dict,
        details: dict,
        duration_ms: int | None = None,
    ) -> int:
        """Salva resultado de auditoria de documentação; retorna o id inserido."""
        res = await self._audits.insert(
            {
                "repo_path": repo_path,
                "score": score,
                "grade": grade,
                "summary": json.dumps(summary),
                "details": json.dumps(details),
                "duration_ms": duration_ms,
                "created_at": _now(),
            },
            user_id=_SYSTEM_USER,
        )
        return int(res.returned_id) if res.returned_id is not None else 0

    async def list_audits(
        self,
        repo_path: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Lista auditorias, mais recentes primeiro (created_at DESC, id DESC de desempate)."""
        res = await self._audits.find(
            where={"repo_path": repo_path} if repo_path else None,
            order_by=[
                Sort(column="created_at", direction=SortDirection.DESC),
                Sort(column="id", direction=SortDirection.DESC),
            ],
            limit=limit,
        )
        return [self._shape_audit(r) for r in res.rows()]

    # ── DOCUMENT INDEX OPERATIONS ────────────────────────────────────────────── #

    async def upsert_doc_index(
        self,
        repo_path: str,
        file_path: str,
        doc_type: str | None,
        title: str | None,
        word_count: int,
        last_modified: str | None,
        content_hash: str | None,
    ) -> None:
        """Insere ou atualiza documento no índice (upsert por chave natural)."""
        await self._doc_index.upsert(
            {
                "repo_path": repo_path,
                "file_path": file_path,
                "doc_type": doc_type,
                "doc_title": title,
                "word_count": word_count,
                "last_modified": last_modified,
                "content_hash": content_hash,
                "created_at": _now(),
            },
            conflict_columns=["repo_path", "file_path"],
            user_id=_SYSTEM_USER,
        )

    async def search_index(self, repo_path: str, query: str) -> list[dict[str, Any]]:
        """Busca documentos no índice cujo file_path contém `query` (case-insensitive).

        Filtro em Python sobre `find().rows()` (dado pequeno; evita LIKE e mantém o
        orm-lint limpo), espelhando a semântica do `title ILIKE %query%` legado — onde
        a coluna `title` guardava o file_path."""
        res = await self._doc_index.find(
            where={"repo_path": repo_path},
            order_by=[Sort(column="file_path", direction=SortDirection.ASC)],
        )
        needle = query.lower()
        return [self._shape_index(r) for r in res.rows() if needle in (r.get("file_path") or "").lower()]

    async def get_index(self, repo_path: str) -> list[dict[str, Any]]:
        """Retorna índice completo de um repositório (ordenado por file_path)."""
        res = await self._doc_index.find(
            where={"repo_path": repo_path},
            order_by=[Sort(column="file_path", direction=SortDirection.ASC)],
        )
        return [self._shape_index(r) for r in res.rows()]
