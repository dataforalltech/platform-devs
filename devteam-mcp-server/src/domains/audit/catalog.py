"""Catálogo de tools + dispatcher do domínio *audit* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `audit-mcp-server/src/server/mcp_server.py`:
mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o ``_dispatch``
(roteamento op → handler). O que ficou de FORA é o boot/serve/segurança (FastAPI, PEP
inner-token, stdio, tenant plumbing) — isso é responsabilidade do AGREGADOR
(`src/server/mcp_server.py`), compartilhado por todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.audit_<op>`` (namespace do server consolidado +
    nome de tool já prefixado pelo domínio — o gateway não deriva por nome, então a
    capability é o id estável).
  * ``required_scope`` passa a ``audit:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool do domínio (data_domain=compliance), só troca o antigo prefixo de namespace
    ``audit-mcp`` pelo domínio canônico ``audit``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo (``run_audit``);
    o ``plugin.register()`` prefixa (``audit_run_audit``) e o ``plugin.dispatch`` retira o
    prefixo antes de chamar ``dispatch`` daqui — a lógica de roteamento copiada do
    server-fonte fica byte-a-byte idêntica.
  * O ``_run_tool`` do fonte (schema-ensure + ``for_tenant`` + ``AuditStore(session)``)
    some: o agregador já garante o schema e abre a sessão tenant-scoped, e o
    ``plugin.dispatch`` constrói a ``AuditStore``. As ``settings`` (``AuditSettings``,
    com ``policies_path``/token do GitHub) são dep de RUNTIME construída aqui via
    ``get_settings()`` — o corpo de roteamento (``_dispatch``) é do fonte, byte-a-byte.
"""

from __future__ import annotations

from typing import Any

from .config.settings import AuditSettings, get_settings
from .db.store import AuditStore
from .tools.approval_tool import submit_audit_approval
from .tools.audit_tool import get_audit_status, run_audit
from .tools.checklist_tool import get_compliance_checklist
from .tools.gate_tool import get_audit_gate_result
from .tools.policy_tool import get_compliance_policy, set_service_criticality
from .tools.report_tool import get_audit_report, list_audits

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "audit"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <domain>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Mutação → verbo :write; consulta
# → :read. Os schemas abaixo são os do server-fonte, byte-a-byte (sem estreitamento:
# o audit não declarava ``additionalProperties`` — não o adicionamos aqui).
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    return s


def _meta(cap: str, scope: str, rtype: str, domain: str, desc: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": desc,
        # capability = <namespace do server consolidado>.<domínio>_<op>
        "capability": f"devteam-mcp.{DOMAIN}_{cap}",
        # required_scope = <domínio>:<recurso>:<ação> (least-privilege por-tool intacto)
        "required_scope": f"{DOMAIN}:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "run_audit": _meta(
        "run_audit",
        "audit:write",
        "audit",
        "compliance",
        "Executa auditoria completa de um repo em um ambiente",
        _schema(
            {
                "service": dict(_STR, description="Nome do serviço"),
                "repo": dict(_STR, description="Nome do repositório"),
                "env": dict(_STR, description="Ambiente: dev, hml, prod", enum=["dev", "hml", "prod"]),
                "repo_path": dict(
                    _STR,
                    description="Caminho local do repo (opcional, tenta resolver automaticamente)",
                ),
            },
            required=["service", "repo", "env"],
        ),
    ),
    "get_audit_status": _meta(
        "get_audit_status",
        "audit:read",
        "audit",
        "compliance",
        "Retorna status da auditoria mais recente de um serviço/ambiente",
        _schema(
            {
                "service": dict(_STR, description="Nome do serviço"),
                "env": dict(_STR, description="Ambiente: dev, hml, prod", enum=["dev", "hml", "prod"]),
            },
            required=["service", "env"],
        ),
    ),
    "get_compliance_policy": _meta(
        "get_compliance_policy",
        "policy:read",
        "policy",
        "compliance",
        "Retorna política de conformidade para um ambiente",
        _schema(
            {
                "env": dict(_STR, description="Ambiente: dev, hml, prod", enum=["dev", "hml", "prod"]),
            },
            required=["env"],
        ),
    ),
    "get_compliance_checklist": _meta(
        "get_compliance_checklist",
        "checklist:read",
        "checklist",
        "compliance",
        "Retorna checklist dinâmico para um repo/ambiente (preview sem persistir)",
        _schema(
            {
                "service": dict(_STR, description="Nome do serviço"),
                "repo": dict(_STR, description="Nome do repositório"),
                "env": dict(_STR, description="Ambiente: dev, hml, prod", enum=["dev", "hml", "prod"]),
            },
            required=["service", "repo", "env"],
        ),
    ),
    "submit_audit_approval": _meta(
        "submit_audit_approval",
        "approval:write",
        "approval",
        "compliance",
        "Submete aprovação ou rejeição manual de uma auditoria",
        _schema(
            {
                "audit_id": dict(_STR, description="ID da auditoria (audit_...)"),
                "approved_by": dict(_STR, description="Identificador de quem aprova"),
                "decision": dict(
                    _STR,
                    description="Decisão: approved ou rejected",
                    enum=["approved", "rejected"],
                ),
                "role": dict(_STR, description="Role do aprovador (developer, lead, architect)"),
                "notes": dict(_STR, description="Notas da aprovação"),
            },
            required=["audit_id", "approved_by", "decision"],
        ),
    ),
    "get_audit_report": _meta(
        "get_audit_report",
        "report:read",
        "report",
        "compliance",
        "Retorna relatório consolidado de conformidade",
        _schema(
            {
                "service": dict(_STR, description="Filtro por serviço (opcional)"),
                "env": dict(_STR, description="Filtro por ambiente (opcional)"),
                "period_days": dict(_INT, description="Período de relatório em dias (default: 30)"),
            }
        ),
    ),
    "list_audits": _meta(
        "list_audits",
        "audit:read",
        "audit",
        "compliance",
        (
            "Lista auditorias de conformidade persistidas, com filtros opcionais por "
            "status, ambiente e serviço e limite de resultados."
        ),
        _schema(
            {
                "status": dict(_STR, description="Filtro por status"),
                "env": dict(_STR, description="Filtro por ambiente"),
                "service": dict(_STR, description="Filtro por serviço"),
                "limit": dict(_INT, description="Limite de resultados (default: 50)"),
            }
        ),
    ),
    "set_service_criticality": _meta(
        "set_service_criticality",
        "criticality:write",
        "criticality",
        "compliance",
        "Define nível de criticidade de um serviço",
        _schema(
            {
                "service": dict(_STR, description="Nome do serviço"),
                "criticality": dict(
                    _STR,
                    description="Nível de criticidade",
                    enum=["low", "medium", "high", "critical"],
                ),
                "updated_by": dict(_STR, description="Quem está atualizando"),
            },
            required=["service", "criticality", "updated_by"],
        ),
    ),
    "get_audit_gate_result": _meta(
        "get_audit_gate_result",
        "gate:read",
        "gate",
        "compliance",
        "Retorna resultado do gate audit_compliance para integração com pipeline-mcp",
        _schema(
            {
                "service": dict(_STR, description="Nome do serviço"),
                "env": dict(_STR, description="Ambiente: dev, hml, prod", enum=["dev", "hml", "prod"]),
            },
            required=["service", "env"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant NÃO viaja nos args, INV-3) ──────
# Corpo do ``_dispatch`` do server-fonte, byte-a-byte (mesma assinatura interna
# ``(name, args, settings, store)``). A ``dispatch`` pública abaixo adere ao contrato
# uniforme ``(name, args, store)`` do agregador, construindo as ``settings`` de runtime.


async def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: AuditSettings,
    store: AuditStore,
) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    if name == "run_audit":
        return await run_audit(
            store,
            settings,
            service=args["service"],
            repo=args["repo"],
            env=args["env"],
            repo_path=args.get("repo_path"),
        )
    if name == "get_audit_status":
        return await get_audit_status(store, settings, service=args["service"], env=args["env"])
    if name == "get_compliance_policy":
        return await get_compliance_policy(store, settings, env=args["env"])
    if name == "get_compliance_checklist":
        return await get_compliance_checklist(
            store, settings, service=args["service"], repo=args["repo"], env=args["env"]
        )
    if name == "submit_audit_approval":
        return await submit_audit_approval(
            store,
            settings,
            audit_id=args["audit_id"],
            approved_by=args["approved_by"],
            decision=args["decision"],
            role=args.get("role"),
            notes=args.get("notes"),
        )
    if name == "get_audit_report":
        return await get_audit_report(
            store,
            settings,
            service=args.get("service"),
            env=args.get("env"),
            period_days=args.get("period_days", 30),
        )
    if name == "list_audits":
        return await list_audits(
            store,
            settings,
            status=args.get("status"),
            env=args.get("env"),
            service=args.get("service"),
            limit=args.get("limit", 50),
        )
    if name == "set_service_criticality":
        return await set_service_criticality(
            store,
            settings,
            service=args["service"],
            criticality=args["criticality"],
            updated_by=args["updated_by"],
        )
    if name == "get_audit_gate_result":
        return await get_audit_gate_result(store, settings, service=args["service"], env=args["env"])
    raise KeyError(name)


async def dispatch(name: str, args: dict[str, Any], store: AuditStore) -> dict[str, Any]:
    """Despacha a chamada (async). ``name`` é o nome de op SEM prefixo de domínio (o
    ``plugin.dispatch`` já o retirou) e ``store`` já está ligado ao pool do tenant.

    As ``settings`` (``AuditSettings`` — token/org do GitHub, ``policies_path``) são dep
    de RUNTIME construída aqui via ``get_settings()`` (não no import/smoke) e repassada
    ao ``_dispatch`` do server-fonte, preservando a assinatura/roteamento byte-a-byte."""
    settings = get_settings()
    return await _dispatch(name, args, settings, store)
