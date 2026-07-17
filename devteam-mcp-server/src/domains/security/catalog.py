"""Catálogo de tools + dispatcher do domínio *security* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `security-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler, aqui renomeado ``dispatch``). O que ficou de
FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) —
isso é responsabilidade do AGREGADOR (`src/server/mcp_server.py`), compartilhado por
todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.security_<op>`` (namespace do server
    consolidado + nome de tool já prefixado pelo domínio — o gateway não deriva por
    nome, então a capability é o id estável).
  * ``required_scope`` passa a ``security:<recurso>:<ação>`` — PRESERVA o
    least-privilege por-tool do domínio (data_domain=security), só troca o antigo
    prefixo de namespace ``security-mcp`` pelo domínio canônico ``security``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_threat_model``); o ``plugin.register()`` prefixa
    (``security_save_threat_model``) e o ``plugin.dispatch`` retira o prefixo antes de
    chamar ``dispatch`` daqui — assim a lógica de roteamento copiada do server-fonte
    fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import SecurityStore
from .tools import (
    delete_cvss_assessment,
    delete_security_artifact,
    delete_security_control,
    delete_threat_model,
    generate_api_security_spec,
    generate_compliance_report,
    generate_security_controls,
    generate_security_handbook,
    get_cvss_assessment,
    get_security_artifact,
    get_security_control,
    get_threat_model,
    list_cvss_assessments,
    list_security_artifacts,
    list_security_controls,
    list_threat_models,
    save_cvss_assessment,
    save_security_artifact,
    save_threat_model,
    set_security_control,
    update_threat_model,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "security"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <domain>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consultas (list/get) usam :read;
# mutações (save/set/update/delete) usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props}
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
    # ── Threat Models ──────────────────────────────────────────────────────── #
    "save_threat_model": _meta(
        "save_threat_model",
        "threat_model:write",
        "threat_model",
        "security",
        "Persiste um modelo de ameaças fornecido pelo agente (as ameaças vêm do agente).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo."),
                "methodology": dict(_STR, description="Metodologia (STRIDE/PASTA/...; default STRIDE)."),
                "title": dict(_STR, description="Título do modelo (opcional)."),
                "components": dict(_ARR, description="Componentes do sistema (opcional)."),
                "threats": dict(_ARR, description="Ameaças identificadas pelo agente (opcional)."),
                "summary": dict(_STR, description="Sumário/escopo da avaliação (opcional)."),
                "status": dict(_STR, description="Status do modelo (opcional)."),
            },
            required=["system_name"],
        ),
    ),
    "list_threat_models": _meta(
        "list_threat_models",
        "threat_model:read",
        "threat_model",
        "security",
        "Lista modelos de ameaças persistidos, com filtros opcionais.",
        _schema(
            {
                "system_name": dict(_STR, description="Filtrar por sistema (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_threat_model": _meta(
        "get_threat_model",
        "threat_model:read",
        "threat_model",
        "security",
        "Retorna um modelo de ameaças persistido (componentes/ameaças/sumário) por id.",
        _schema({"id": dict(_INT, description="Id do modelo.")}, required=["id"]),
    ),
    "update_threat_model": _meta(
        "update_threat_model",
        "threat_model:write",
        "threat_model",
        "security",
        "Atualiza campos mutáveis de um modelo de ameaças.",
        _schema(
            {
                "id": dict(_INT, description="Id do modelo."),
                "methodology": dict(_STR, description="Nova metodologia (opcional)."),
                "title": dict(_STR, description="Novo título (opcional)."),
                "components": dict(_ARR, description="Novos componentes (opcional)."),
                "threats": dict(_ARR, description="Novas ameaças (opcional)."),
                "summary": dict(_STR, description="Novo sumário (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_threat_model": _meta(
        "delete_threat_model",
        "threat_model:write",
        "threat_model",
        "security",
        "Soft-delete de um modelo de ameaças por id.",
        _schema({"id": dict(_INT, description="Id do modelo.")}, required=["id"]),
    ),
    # ── Security Controls (upsert por (system_name, control_key)) ───────────────── #
    "set_security_control": _meta(
        "set_security_control",
        "security_control:write",
        "security_control",
        "security",
        "Define (upsert) um controle de segurança por (system_name, control_key).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo (parte da chave natural)."),
                "control_key": dict(_STR, description="Chave do controle (parte da chave natural)."),
                "name": dict(_STR, description="Nome do controle (opcional)."),
                "control_type": dict(_STR, description="Tipo (technical/operational; opcional)."),
                "framework_ref": dict(_STR, description="Referência de framework (nist_csf/...; opcional)."),
                "details": dict(_OBJ, description="Detalhes do controle (opcional)."),
                "status": dict(_STR, description="Status do controle (opcional)."),
            },
            required=["system_name", "control_key"],
        ),
    ),
    "list_security_controls": _meta(
        "list_security_controls",
        "security_control:read",
        "security_control",
        "security",
        "Lista controles de segurança persistidos, com filtros opcionais.",
        _schema(
            {
                "system_name": dict(_STR, description="Filtrar por sistema (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_security_control": _meta(
        "get_security_control",
        "security_control:read",
        "security_control",
        "security",
        "Retorna um controle de segurança por (system_name, control_key).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo."),
                "control_key": dict(_STR, description="Chave do controle."),
            },
            required=["system_name", "control_key"],
        ),
    ),
    "delete_security_control": _meta(
        "delete_security_control",
        "security_control:write",
        "security_control",
        "security",
        "Soft-delete de um controle de segurança por (system_name, control_key).",
        _schema(
            {
                "system_name": dict(_STR, description="Sistema alvo."),
                "control_key": dict(_STR, description="Chave do controle."),
            },
            required=["system_name", "control_key"],
        ),
    ),
    # ── CVSS Assessments ───────────────────────────────────────────────────── #
    "save_cvss_assessment": _meta(
        "save_cvss_assessment",
        "cvss:write",
        "cvss",
        "security",
        "Persiste uma avaliação CVSS. Se score/severity/metrics não vierem, calcula-os do vetor.",
        _schema(
            {
                "vector": dict(_STR, description="Vetor CVSS 3.1 (ex: CVSS:3.1/AV:N/AC:L/...)."),
                "label": dict(_STR, description="Rótulo/CVE da vulnerabilidade (opcional)."),
                "base_score": dict(_NUM, description="Score (opcional; calculado se ausente)."),
                "severity": dict(_STR, description="Severidade (opcional; calculada se ausente)."),
                "metrics": dict(_OBJ, description="Métricas do vetor (opcional; calculadas se ausente)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["vector"],
        ),
    ),
    "list_cvss_assessments": _meta(
        "list_cvss_assessments",
        "cvss:read",
        "cvss",
        "security",
        "Lista avaliações CVSS persistidas, com filtros opcionais.",
        _schema(
            {
                "severity": dict(_STR, description="Filtrar por severidade (opcional)."),
                "label": dict(_STR, description="Filtrar por rótulo/CVE (opcional)."),
            }
        ),
    ),
    "get_cvss_assessment": _meta(
        "get_cvss_assessment",
        "cvss:read",
        "cvss",
        "security",
        "Retorna uma avaliação CVSS persistida (vetor/score/severidade/métricas) por id.",
        _schema({"id": dict(_INT, description="Id da avaliação.")}, required=["id"]),
    ),
    "delete_cvss_assessment": _meta(
        "delete_cvss_assessment",
        "cvss:write",
        "cvss",
        "security",
        "Soft-delete de uma avaliação CVSS por id.",
        _schema({"id": dict(_INT, description="Id da avaliação.")}, required=["id"]),
    ),
    # ── Security Artifacts (histórico append-only) ─────────────────────────── #
    "save_security_artifact": _meta(
        "save_security_artifact",
        "artifact:write",
        "artifact",
        "security",
        "Persiste um artefato de segurança (relatório/scan) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: incident_plan|attack_surface|compliance|code_review|"
                        "dep_risk|secrets_scan|headers|password_policy."
                    ),
                ),
                "target": dict(_STR, description="Alvo (sistema/serviço/endpoint/arquivo)."),
                "content": dict(_STR, description="Relatório/texto gerado pelo agente (opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target"],
        ),
    ),
    "list_security_artifacts": _meta(
        "list_security_artifacts",
        "artifact:read",
        "artifact",
        "security",
        "Lista artefatos de segurança persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_security_artifact": _meta(
        "get_security_artifact",
        "artifact:read",
        "artifact",
        "security",
        "Retorna um artefato de segurança por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_security_artifact": _meta(
        "delete_security_artifact",
        "artifact:write",
        "artifact",
        "security",
        "Soft-delete de um artefato de segurança por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com
    # :read p/ consultas e :write p/ mutações do estado do tenant. Geradores não
    # LEEM nem GRAVAM estado — só computam conteúdo de segurança — então nenhum dos
    # dois cabe. Escolha: nova ação `:generate` sobre resource_type=`artifact` (o
    # mesmo domínio dos artefatos de segurança produzidos): least-privilege real (um
    # token só de geração não abre leitura/escrita de artefatos persistidos).
    "generate_security_controls": _meta(
        "generate_security_controls",
        "artifact:generate",
        "artifact",
        "security",
        "Gera uma matriz de controles de segurança (controles × assets) determinística a partir da spec.",
        _schema(
            {
                "framework": dict(_STR, description="Framework de referência (nist_csf/iso_27001/cis/...)."),
                "assets": dict(_ARR, description="Assets [str | {name}] que compõem as colunas (opcional)."),
                "controls": dict(
                    _ARR,
                    description="Controles [{key|control_key,name?,category?,framework_ref?,applies_to?}].",
                ),
            },
            required=["framework", "controls"],
        ),
    ),
    "generate_api_security_spec": _meta(
        "generate_api_security_spec",
        "artifact:generate",
        "artifact",
        "security",
        "Gera um spec de segurança de API (YAML) determinístico a partir de endpoints/auth/ameaças.",
        _schema(
            {
                "endpoints": dict(
                    _ARR,
                    description="Endpoints [{path,method?,auth_required?,scopes?}].",
                ),
                "auth": dict(_OBJ, description="Esquema de auth (string ou objeto; default bearer_jwt)."),
                "threats": dict(_ARR, description="Ameaças [str | {id?,description,...}] (opcional)."),
                "title": dict(_STR, description="Título do spec (opcional)."),
            },
            required=["endpoints"],
        ),
    ),
    "generate_compliance_report": _meta(
        "generate_compliance_report",
        "artifact:generate",
        "artifact",
        "security",
        "Gera um relatório de compliance (markdown) determinístico com sumário e índice de conformidade.",
        _schema(
            {
                "standard": dict(_STR, description="Padrão avaliado (SOC2/ISO27001/LGPD/...)."),
                "findings": dict(
                    _ARR,
                    description="Achados [{control,status,note?}]; status ex.: pass|partial|fail|na.",
                ),
                "title": dict(_STR, description="Título do relatório (opcional)."),
            },
            required=["standard", "findings"],
        ),
    ),
    "generate_security_handbook": _meta(
        "generate_security_handbook",
        "artifact:generate",
        "artifact",
        "security",
        "Gera um handbook de segurança (markdown com índice) determinístico a partir das seções.",
        _schema(
            {
                "sections": dict(_ARR, description="Seções [{title,content?,items?}]."),
                "title": dict(_STR, description="Título do handbook (default 'Security Handbook')."),
            },
            required=["sections"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: SecurityStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). ``name`` é o nome de op SEM prefixo de
    domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_security_controls":
        return generate_security_controls(args)
    if name == "generate_api_security_spec":
        return generate_api_security_spec(args)
    if name == "generate_compliance_report":
        return generate_compliance_report(args)
    if name == "generate_security_handbook":
        return generate_security_handbook(args)
    # ── Threat Models ──────────────────────────────────────────────────────── #
    if name == "save_threat_model":
        return await save_threat_model(
            store,
            system_name=args["system_name"],
            methodology=args.get("methodology", "STRIDE"),
            title=args.get("title"),
            components=args.get("components"),
            threats=args.get("threats"),
            summary=args.get("summary"),
            status=args.get("status"),
        )
    if name == "list_threat_models":
        return await list_threat_models(store, system_name=args.get("system_name"), status=args.get("status"))
    if name == "get_threat_model":
        return await get_threat_model(store, model_id=args["id"])
    if name == "update_threat_model":
        return await update_threat_model(
            store,
            model_id=args["id"],
            methodology=args.get("methodology"),
            title=args.get("title"),
            components=args.get("components"),
            threats=args.get("threats"),
            summary=args.get("summary"),
            status=args.get("status"),
        )
    if name == "delete_threat_model":
        return await delete_threat_model(store, model_id=args["id"])
    # ── Security Controls ──────────────────────────────────────────────────── #
    if name == "set_security_control":
        return await set_security_control(
            store,
            system_name=args["system_name"],
            control_key=args["control_key"],
            name=args.get("name"),
            control_type=args.get("control_type"),
            framework_ref=args.get("framework_ref"),
            details=args.get("details"),
            status=args.get("status"),
        )
    if name == "list_security_controls":
        return await list_security_controls(
            store, system_name=args.get("system_name"), status=args.get("status")
        )
    if name == "get_security_control":
        return await get_security_control(
            store, system_name=args["system_name"], control_key=args["control_key"]
        )
    if name == "delete_security_control":
        return await delete_security_control(
            store, system_name=args["system_name"], control_key=args["control_key"]
        )
    # ── CVSS Assessments ───────────────────────────────────────────────────── #
    if name == "save_cvss_assessment":
        return await save_cvss_assessment(
            store,
            vector=args["vector"],
            label=args.get("label"),
            base_score=args.get("base_score"),
            severity=args.get("severity"),
            metrics=args.get("metrics"),
            status=args.get("status"),
        )
    if name == "list_cvss_assessments":
        return await list_cvss_assessments(store, severity=args.get("severity"), label=args.get("label"))
    if name == "get_cvss_assessment":
        return await get_cvss_assessment(store, assessment_id=args["id"])
    if name == "delete_cvss_assessment":
        return await delete_cvss_assessment(store, assessment_id=args["id"])
    # ── Security Artifacts ─────────────────────────────────────────────────── #
    if name == "save_security_artifact":
        return await save_security_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args.get("content"),
            meta=args.get("meta"),
        )
    if name == "list_security_artifacts":
        return await list_security_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_security_artifact":
        return await get_security_artifact(store, artifact_id=args["id"])
    if name == "delete_security_artifact":
        return await delete_security_artifact(store, artifact_id=args["id"])
    raise KeyError(name)
