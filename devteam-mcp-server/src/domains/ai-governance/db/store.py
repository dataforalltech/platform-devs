"""Stores do ai-governance-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescritos dos file stores (JSON-por-arquivo + JSONL append-only) para o **Repository**
de alto nível + Query IR, ligados ao pool **do tenant** (resolvido credencial-zero via
`for_tenant`/`get_pool_for_tenant`, ORM-H-12). Rodam dual-db: o mesmo código serve MySQL
(banco-por-tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Dois stores mutáveis, tenant-scoped:

  * ``SuggestionStore`` — a mural cross-repo. Chave natural ``suggestion_id`` (o antigo
    id-arquivo sortable). CRUD via ``find``/``insert``/``update_where``. Mapeia a linha
    do DB (``SuggestionRow``, colunas JSON serializadas) para o modelo de domínio
    ``Suggestion`` — a API pública das tools é preservada intacta.
  * ``AuditStore`` — a trilha append-only de ``validate_agent_decision``. ``insert`` por
    decisão; ``query``/``stats`` fazem full-scan + agregação em Python (dado pequeno,
    ordenado por ``id DESC``; evita GROUP BY e mantém o orm-lint limpo).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`) — o ator de negócio real (source_agent/
by) continua sendo string em colunas próprias.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models.suggestion import (
    StatusChange,
    Suggestion,
    SuggestionCategory,
    SuggestionFilters,
    SuggestionSeverity,
    SuggestionStatus,
)
from .models import DecisionAuditRow, SuggestionRow
from .schema import AUDIT_TABLE, SUGGESTIONS_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O ator de negócio real viaja em colunas próprias (source_agent, by, ...).
_SYSTEM_USER = 0

# Mesma regex do store antigo: id sortable YYYYMMDDTHHMMSSffffff-XXXXXXXX.
_ID_RE = re.compile(r"^\d{8}T\d{12}-[a-f0-9]{8}$")


class SuggestionStoreError(ValueError):
    """Erro de persistência ou validação de sugestão (id inválido, não encontrada)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _loads_list(value: Any) -> list[Any]:
    """Desserializa uma coluna JSON TEXT em lista (robusta a null/corrompido)."""
    if isinstance(value, str) and value:
        try:
            data = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []
    if isinstance(value, list):
        return value
    return []


def _loads_obj(value: Any) -> dict[str, Any]:
    """Desserializa uma coluna JSON TEXT em dict (robusta a null/corrompido)."""
    if isinstance(value, str) and value:
        try:
            data = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


class SuggestionStore:
    """Store tenant-scoped da mural cross-repo (1 repositório ORM).

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria o
    repositório canônico por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._repo = session.repository(SuggestionRow, table_name=SUGGESTIONS_TABLE)

    # -- ID (chave natural sortable, preservada do store antigo) --------------- #

    @staticmethod
    def _generate_id() -> str:
        # Microssegundos garantem ordering monotônica; o sufixo UUID resolve colisão.
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        suffix = uuid.uuid4().hex[:8]
        return f"{ts}-{suffix}"

    @staticmethod
    def _validate_id(suggestion_id: str) -> None:
        if not _ID_RE.match(suggestion_id or ""):
            raise SuggestionStoreError(
                f"id inválido: {suggestion_id!r}. Formato esperado: YYYYMMDDTHHMMSSffffff-XXXXXXXX"
            )

    # -- mapeamento linha <-> domínio ------------------------------------------ #

    @staticmethod
    def _to_domain(row: dict[str, Any]) -> Suggestion:
        history = [StatusChange(**c) for c in _loads_list(row.get("status_history")) if isinstance(c, dict)]
        # category/severity/status são Literal no domínio; o Pydantic valida os valores
        # vindos do DB no construtor. Passamos como Any (a coluna sempre traz um válido).
        category: Any = row.get("category")
        severity: Any = row.get("severity")
        status: Any = row.get("status") or "pending"
        return Suggestion(
            id=str(row["suggestion_id"]),
            created_at=str(row.get("created_at") or ""),
            source_agent=str(row.get("source_agent") or ""),
            source_repo=row.get("source_repo"),
            target_repo=str(row.get("target_repo") or ""),
            target_repo_canonical=row.get("target_repo_canonical"),
            category=category,
            severity=severity,
            title=str(row.get("title") or ""),
            description=str(row.get("description") or ""),
            related_files=[str(f) for f in _loads_list(row.get("related_files"))],
            references=[str(r) for r in _loads_list(row.get("reference_links"))],
            status=status,
            status_history=history,
        )

    async def _row(self, suggestion_id: str) -> dict[str, Any] | None:
        res = await self._repo.find(where={"suggestion_id": suggestion_id}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    # -- operações (mesma superfície do store antigo) -------------------------- #

    async def create(
        self,
        *,
        source_agent: str,
        target_repo: str,
        category: SuggestionCategory,
        severity: SuggestionSeverity,
        title: str,
        description: str,
        source_repo: str | None = None,
        related_files: list[str] | None = None,
        references: list[str] | None = None,
        target_repo_canonical: str | None = None,
    ) -> Suggestion:
        """Cria uma nova sugestão e persiste no banco do tenant."""
        now = _now_iso()
        suggestion_id = self._generate_id()
        history = [StatusChange(ts=now, status="pending", note="Criada", by=source_agent)]
        await self._repo.insert(
            {
                "suggestion_id": suggestion_id,
                "created_at": now,
                "source_agent": source_agent,
                "source_repo": source_repo,
                "target_repo": target_repo,
                "target_repo_canonical": target_repo_canonical,
                "category": category,
                "severity": severity,
                "title": title,
                "description": description,
                "related_files": json.dumps(related_files or [], ensure_ascii=False),
                "reference_links": json.dumps(references or [], ensure_ascii=False),
                "status": "pending",
                "status_history": json.dumps([c.model_dump() for c in history], ensure_ascii=False),
            },
            user_id=_SYSTEM_USER,
        )
        row = await self._row(suggestion_id)
        if row is None:
            raise SuggestionStoreError(f"falha ao persistir sugestão {suggestion_id!r}")
        return self._to_domain(row)

    async def get(self, suggestion_id: str) -> Suggestion | None:
        self._validate_id(suggestion_id)
        row = await self._row(suggestion_id)
        return self._to_domain(row) if row is not None else None

    async def list(self, filters: SuggestionFilters | None = None) -> list[Suggestion]:
        """Lista sugestões aplicando filtros. Ordem: id descendente (mais novos primeiro)."""
        f = filters or SuggestionFilters()
        # Filtros de igualdade simples vão para o WHERE; target_repo casa target_repo OU
        # target_repo_canonical (OR), então fica no Python (com o limite pós-filtro).
        where: dict[str, Any] = {}
        if f.status:
            where["status"] = f.status
        if f.category:
            where["category"] = f.category
        if f.severity:
            where["severity"] = f.severity
        if f.source_agent:
            where["source_agent"] = f.source_agent
        res = await self._repo.find(
            where=where or None,
            order_by=[Sort(column="suggestion_id", direction=SortDirection.DESC)],
        )
        results: list[Suggestion] = []
        for row in res.rows():
            suggestion = self._to_domain(row)
            if (
                f.target_repo
                and suggestion.target_repo != f.target_repo
                and suggestion.target_repo_canonical != f.target_repo
            ):
                continue
            results.append(suggestion)
            if len(results) >= f.limit:
                break
        return results

    async def update_status(
        self,
        suggestion_id: str,
        new_status: SuggestionStatus,
        *,
        note: str | None = None,
        by: str | None = None,
    ) -> Suggestion:
        self._validate_id(suggestion_id)
        row = await self._row(suggestion_id)
        if row is None:
            raise SuggestionStoreError(f"sugestão não encontrada: {suggestion_id!r}")
        current = self._to_domain(row)
        if new_status == current.status and not note:
            # Sem mudança real — não polui o histórico.
            return current
        change = StatusChange(ts=_now_iso(), status=new_status, note=note, by=by)
        current.status = new_status
        current.status_history.append(change)
        await self._repo.update_where(
            {"suggestion_id": suggestion_id},
            {
                "status": new_status,
                "status_history": json.dumps(
                    [c.model_dump() for c in current.status_history], ensure_ascii=False
                ),
            },
            user_id=_SYSTEM_USER,
        )
        return current

    async def stats(self) -> dict[str, Any]:
        """Métricas resumidas do store (agregação em Python sobre find().rows())."""
        rows = (await self._repo.find()).rows()
        total = 0
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_target: dict[str, int] = {}
        for row in rows:
            total += 1
            status = str(row.get("status") or "?")
            by_status[status] = by_status.get(status, 0) + 1
            severity = str(row.get("severity") or "?")
            by_severity[severity] = by_severity.get(severity, 0) + 1
            target = str(row.get("target_repo_canonical") or row.get("target_repo") or "?")
            by_target[target] = by_target.get(target, 0) + 1
        return {
            "total": total,
            "by_status": dict(sorted(by_status.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "by_target": dict(sorted(by_target.items(), key=lambda x: -x[1])),
            "table": SUGGESTIONS_TABLE,
        }


class AuditStore:
    """Store tenant-scoped da trilha append-only de decisões (1 repositório ORM)."""

    def __init__(self, session: Any) -> None:
        self._repo = session.repository(DecisionAuditRow, table_name=AUDIT_TABLE)

    async def record(self, result: dict[str, Any], input_summary: dict[str, Any] | None = None) -> None:
        """Persiste um resultado de ``validate_agent_decision`` na trilha (append)."""
        summary = input_summary or result.get("input_summary", {}) or {}
        violations = result.get("violations", []) or []
        required_actions = result.get("required_actions", []) or []
        flags = {
            "changes_contracts": summary.get("changes_contracts", False),
            "adds_fallback": summary.get("adds_fallback", False),
            "adds_dependency": summary.get("adds_dependency", False),
            "modifies_security": summary.get("modifies_security", False),
        }
        await self._repo.insert(
            {
                "ts": _now_iso(),
                "repo": summary.get("repository_name", "unknown"),
                "task_description": (summary.get("task_description") or "")[:200],
                "approved": 1 if result.get("approved", True) else 0,
                "risk_level": result.get("risk_level", "unknown"),
                "violations_count": len(violations),
                "violations": json.dumps(violations, ensure_ascii=False),
                "required_actions_count": len(required_actions),
                "required_actions": json.dumps(required_actions, ensure_ascii=False),
                "affected_layers": json.dumps(summary.get("affected_layers", []) or [], ensure_ascii=False),
                "affected_files_count": summary.get("affected_files_count", 0),
                "flags": json.dumps(flags, ensure_ascii=False),
            },
            user_id=_SYSTEM_USER,
        )

    @staticmethod
    def _entry(row: dict[str, Any]) -> dict[str, Any]:
        """Reconstrói a forma de linha do log (back-compat com o JSONL antigo)."""
        return {
            "ts": row.get("ts"),
            "repo": row.get("repo", "unknown"),
            "task_description": row.get("task_description", ""),
            "approved": bool(row.get("approved")),
            "risk_level": row.get("risk_level", "unknown"),
            "violations_count": row.get("violations_count", 0),
            "violations": _loads_list(row.get("violations")),
            "required_actions_count": row.get("required_actions_count", 0),
            "required_actions": _loads_list(row.get("required_actions")),
            "affected_layers": _loads_list(row.get("affected_layers")),
            "affected_files_count": row.get("affected_files_count", 0),
            "flags": _loads_obj(row.get("flags")),
        }

    async def query(
        self,
        *,
        repo: str | None = None,
        risk_level: str | None = None,
        approved: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Entradas filtradas em ordem cronológica reversa (mais recente primeiro).

        risk_level/approved casam por igualdade (WHERE); repo é substring
        case-insensitive (Python). A paginação (offset/limit) é aplicada pós-filtro.
        """
        limit = min(limit, 500)
        where: dict[str, Any] = {}
        if risk_level:
            where["risk_level"] = risk_level
        if approved is not None:
            where["approved"] = 1 if approved else 0
        res = await self._repo.find(
            where=where or None, order_by=[Sort(column="id", direction=SortDirection.DESC)]
        )
        entries: list[dict[str, Any]] = []
        for row in res.rows():
            if repo and repo.lower() not in str(row.get("repo") or "").lower():
                continue
            entries.append(self._entry(row))
        return entries[offset : offset + limit]

    async def stats(self) -> dict[str, Any]:
        """Estatísticas agregadas da trilha (full-scan + agregação em Python)."""
        rows = (await self._repo.find()).rows()
        total = 0
        approved_count = 0
        blocked_count = 0
        risk_counts: dict[str, int] = {}
        repo_counts: dict[str, int] = {}
        violation_counts: dict[str, int] = {}
        for row in rows:
            total += 1
            if row.get("approved"):
                approved_count += 1
            else:
                blocked_count += 1
            risk = str(row.get("risk_level") or "unknown")
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
            repo = str(row.get("repo") or "unknown")
            repo_counts[repo] = repo_counts.get(repo, 0) + 1
            for violation in _loads_list(row.get("violations")):
                key = str(violation)[:80]
                violation_counts[key] = violation_counts.get(key, 0) + 1
        top_repos = sorted(repo_counts.items(), key=lambda x: -x[1])[:10]
        top_violations = sorted(violation_counts.items(), key=lambda x: -x[1])[:10]
        return {
            "total": total,
            "approved": approved_count,
            "blocked": blocked_count,
            "block_rate": round(blocked_count / total, 3) if total else 0.0,
            "by_risk_level": risk_counts,
            "top_repos": [{"repo": r, "count": c} for r, c in top_repos],
            "top_violations": [{"violation": v, "count": c} for v, c in top_violations],
        }


__all__ = ["SuggestionStore", "AuditStore", "SuggestionStoreError"]
