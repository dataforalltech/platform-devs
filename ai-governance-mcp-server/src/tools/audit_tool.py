"""Tool get_audit_log — consulta a trilha de auditoria de decisões.

Expõe a trilha gerada pelo AuditStore de maneira consultável:
  - Filtros por repo, risk_level, approved.
  - Paginação com offset.
  - Endpoint `stats` com métricas agregadas.

A tool é somente-leitura. Escrita na trilha é responsabilidade do mcp_server.py,
que grava automaticamente após cada chamada bem-sucedida de validate_agent_decision.
"""

from __future__ import annotations

from ..knowledge.audit_store import AuditStore
from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import coerce_bool


def get_audit_log(
    repo: GovernanceRepository,
    audit_store: AuditStore,
    *,
    query: str | None = None,
    filter_repo: str | None = None,
    risk_level: str | None = None,
    approved: bool | str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Consulta a trilha de auditoria de validate_agent_decision.

    Args:
        query:       "stats" para retornar métricas agregadas; omitir para listar.
        filter_repo: Filtro por repositório (substring, case-insensitive).
        risk_level:  Filtro exato: low | medium | high | critical.
        approved:    true → só aprovados; false → só bloqueados.
        limit:       Máximo de registros (1–500; default 50).
        offset:      Paginação — pular os primeiros N resultados.
    """
    if query == "stats":
        return {"stats": audit_store.stats()}

    approved_bool: bool | None = None
    if approved is not None:
        approved_bool = coerce_bool(approved)

    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    entries = audit_store.query(
        repo=filter_repo,
        risk_level=risk_level,
        approved=approved_bool,
        limit=limit,
        offset=offset,
    )

    # Truncar proposed_change a 100 chars na listagem para reduzir payload LLM.
    # Use get_audit_entry(id) para o conteúdo completo quando necessário.
    truncated: list[dict] = []
    for entry in entries:
        e = dict(entry)
        if isinstance(e.get("proposed_change"), str) and len(e["proposed_change"]) > 100:
            e["proposed_change"] = e["proposed_change"][:100] + "…"
        truncated.append(e)

    return {
        "entries": truncated,
        "count": len(truncated),
        "limit": limit,
        "offset": offset,
        "filters": {
            "repo": filter_repo,
            "risk_level": risk_level,
            "approved": approved_bool,
        },
    }
