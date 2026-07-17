"""Catálogo de tools + dispatcher do domínio *product-manager* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `product-manager-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler, aqui exposto como ``dispatch``). O que ficou de
FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) — isso é
responsabilidade do AGREGADOR (`src/server/mcp_server.py`), compartilhado por todos os
domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.product-manager_<op>`` (namespace do server
    consolidado + nome de tool já prefixado pelo domínio — o gateway não deriva por
    nome, então a capability é o id estável).
  * ``required_scope`` passa a ``product-manager:<recurso>:<ação>`` — PRESERVA o
    least-privilege por-tool do domínio (data_domain=product-manager), só troca o antigo
    prefixo de namespace ``product-manager-mcp`` pelo domínio canônico ``product-manager``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_feature_spec``); o ``plugin.register()`` prefixa (``product-manager_save_feature_spec``)
    e o ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim
    a lógica de roteamento copiada do server-fonte fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import ProductManagerStore
from .tools import (
    calculate_rice_score,
    delete_artifact,
    delete_feature_spec,
    delete_gtm_brief,
    delete_product_vision,
    delete_release_plan,
    generate_acceptance_criteria,
    generate_handoff_to_architecture,
    generate_handoff_to_design,
    generate_handoff_to_engineering,
    generate_release_plan,
    get_artifact,
    get_feature_spec,
    get_gtm_brief,
    get_product_vision,
    get_release_plan,
    list_artifacts,
    list_feature_specs,
    list_gtm_briefs,
    list_product_visions,
    list_release_plans,
    save_artifact,
    save_feature_spec,
    save_gtm_brief,
    save_release_plan,
    set_product_vision,
    update_feature_spec,
    update_gtm_brief,
    update_release_plan,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "product-manager"

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
    # ── Feature Specs ──────────────────────────────────────────────────────── #
    "save_feature_spec": _meta(
        "save_feature_spec",
        "feature_spec:write",
        "feature_spec",
        "product-manager",
        "Persiste uma feature spec fornecida pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "feature": dict(_STR, description="Funcionalidade/tema alvo."),
                "content": dict(_OBJ, description="Conteúdo da spec (user_stories/acceptance_criteria/...)."),
                "objective": dict(_STR, description="Objetivo da feature (opcional)."),
                "priority": dict(_STR, description="Prioridade (high/medium/low; opcional)."),
                "status": dict(_STR, description="Status da spec (opcional)."),
            },
            required=["feature", "content"],
        ),
    ),
    "list_feature_specs": _meta(
        "list_feature_specs",
        "feature_spec:read",
        "feature_spec",
        "product-manager",
        "Lista feature specs persistidas, com filtros opcionais.",
        _schema(
            {
                "feature": dict(_STR, description="Filtrar por funcionalidade (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_feature_spec": _meta(
        "get_feature_spec",
        "feature_spec:read",
        "feature_spec",
        "product-manager",
        "Retorna uma feature spec persistida (user stories/critérios de aceite/conteúdo) pelo id informado.",
        _schema({"id": dict(_INT, description="Id da spec.")}, required=["id"]),
    ),
    "update_feature_spec": _meta(
        "update_feature_spec",
        "feature_spec:write",
        "feature_spec",
        "product-manager",
        "Atualiza campos mutáveis de uma feature spec (objective/priority/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da spec."),
                "objective": dict(_STR, description="Novo objetivo (opcional)."),
                "priority": dict(_STR, description="Nova prioridade (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_feature_spec": _meta(
        "delete_feature_spec",
        "feature_spec:write",
        "feature_spec",
        "product-manager",
        "Remove (soft-delete) uma feature spec por id; marca como inativa preservando o histórico "
        "e é idempotente.",
        _schema({"id": dict(_INT, description="Id da spec.")}, required=["id"]),
    ),
    # ── GTM Briefs ─────────────────────────────────────────────────────────── #
    "save_gtm_brief": _meta(
        "save_gtm_brief",
        "gtm_brief:write",
        "gtm_brief",
        "product-manager",
        "Persiste um go-to-market brief fornecido pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "product": dict(_STR, description="Produto/lançamento alvo."),
                "content": dict(
                    _OBJ, description="Conteúdo do brief (target_segment/key_messages/channels/...)."
                ),
                "launch_timing": dict(_STR, description="Janela de lançamento (ex.: 'Q2 2026'; opcional)."),
                "status": dict(_STR, description="Status do brief (opcional)."),
            },
            required=["product", "content"],
        ),
    ),
    "list_gtm_briefs": _meta(
        "list_gtm_briefs",
        "gtm_brief:read",
        "gtm_brief",
        "product-manager",
        "Lista GTM briefs persistidos, com filtros opcionais.",
        _schema(
            {
                "product": dict(_STR, description="Filtrar por produto (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_gtm_brief": _meta(
        "get_gtm_brief",
        "gtm_brief:read",
        "gtm_brief",
        "product-manager",
        "Retorna um go-to-market brief persistido (segmento/mensagens/canais/conteúdo) pelo id informado.",
        _schema({"id": dict(_INT, description="Id do brief.")}, required=["id"]),
    ),
    "update_gtm_brief": _meta(
        "update_gtm_brief",
        "gtm_brief:write",
        "gtm_brief",
        "product-manager",
        "Atualiza campos mutáveis de um GTM brief (launch_timing/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do brief."),
                "launch_timing": dict(_STR, description="Nova janela de lançamento (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_gtm_brief": _meta(
        "delete_gtm_brief",
        "gtm_brief:write",
        "gtm_brief",
        "product-manager",
        "Remove (soft-delete) um go-to-market brief por id; marca como inativo preservando o registro "
        "e é idempotente.",
        _schema({"id": dict(_INT, description="Id do brief.")}, required=["id"]),
    ),
    # ── Release Plans ──────────────────────────────────────────────────────── #
    "save_release_plan": _meta(
        "save_release_plan",
        "release_plan:write",
        "release_plan",
        "product-manager",
        "Persiste um plano de release fornecido pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo."),
                "content": dict(_OBJ, description="Conteúdo do plano (phases/timeline/features_per_phase)."),
                "status": dict(_STR, description="Status do plano (opcional)."),
            },
            required=["product", "content"],
        ),
    ),
    "list_release_plans": _meta(
        "list_release_plans",
        "release_plan:read",
        "release_plan",
        "product-manager",
        "Lista planos de release persistidos, com filtros opcionais.",
        _schema(
            {
                "product": dict(_STR, description="Filtrar por produto (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_release_plan": _meta(
        "get_release_plan",
        "release_plan:read",
        "release_plan",
        "product-manager",
        "Retorna um plano de release persistido (fases/timeline/features por fase) pelo id informado.",
        _schema({"id": dict(_INT, description="Id do plano.")}, required=["id"]),
    ),
    "update_release_plan": _meta(
        "update_release_plan",
        "release_plan:write",
        "release_plan",
        "product-manager",
        "Atualiza campos mutáveis de um plano de release (content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do plano."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_release_plan": _meta(
        "delete_release_plan",
        "release_plan:write",
        "release_plan",
        "product-manager",
        "Soft-delete de um plano de release por id.",
        _schema({"id": dict(_INT, description="Id do plano.")}, required=["id"]),
    ),
    # ── Product Visions (upsert por product) ───────────────────────────────── #
    "set_product_vision": _meta(
        "set_product_vision",
        "product_vision:write",
        "product_vision",
        "product-manager",
        "Define (upsert) a visão de um produto (vision/mission/goals fornecidos pelo agente).",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo (chave natural única)."),
                "vision": dict(_STR, description="Declaração de visão (opcional)."),
                "mission": dict(_STR, description="Declaração de missão (opcional)."),
                "goals": dict(_ARR, description="Objetivos do produto (lista; opcional)."),
                "status": dict(_STR, description="Status da visão (opcional)."),
            },
            required=["product"],
        ),
    ),
    "list_product_visions": _meta(
        "list_product_visions",
        "product_vision:read",
        "product_vision",
        "product-manager",
        "Lista visões de produto persistidas, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_product_vision": _meta(
        "get_product_vision",
        "product_vision:read",
        "product_vision",
        "product-manager",
        "Retorna a visão de um produto persistida (vision/mission/goals) pela chave natural do produto.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    "delete_product_vision": _meta(
        "delete_product_vision",
        "product_vision:write",
        "product_vision",
        "product-manager",
        "Remove (soft-delete) a visão de um produto pela chave natural do produto; preserva o registro "
        "e é idempotente.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "product-manager",
        "Persiste um artefato de produto (documento/texto) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: product_vision|feature_spec|gtm_brief|release_plan|roadmap|"
                        "prd|okr|persona|user_story|discovery|analysis."
                    ),
                ),
                "target": dict(_STR, description="Alvo (produto/feature/segmento)."),
                "content": dict(_STR, description="Documento/texto gerado pelo agente."),
                "fmt": dict(_STR, description="Formato (markdown/json/...; opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "product-manager",
        "Lista artefatos persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_artifact": _meta(
        "get_artifact",
        "artifact:read",
        "artifact",
        "product-manager",
        "Retorna um artefato de produto persistido (documento/texto gerado pelo agente) pelo id informado.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "product-manager",
        "Remove (soft-delete) um artefato de produto por id; marca como inativo preservando o histórico "
        "e é idempotente.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com
    # :read p/ consultas e :write p/ mutações do estado do tenant. Geradores não
    # LEEM nem GRAVAM estado — só computam conteúdo de produto — então nenhum dos
    # dois cabe. Escolha: nova ação `:generate` sobre resource_type=`artifact` (o
    # mesmo domínio dos artefatos de produto produzidos): least-privilege real (um
    # token só de geração não abre leitura/escrita de artefatos persistidos).
    "generate_release_plan": _meta(
        "generate_release_plan",
        "artifact:generate",
        "artifact",
        "product-manager",
        "Gera um plano de release em Markdown determinístico a partir de versão/escopo/milestones.",
        _schema(
            {
                "version": dict(_STR, description="Versão do release (ex.: '2.1.0')."),
                "scope": dict(_ARR, description="Itens de escopo do release (opcional)."),
                "milestones": dict(_ARR, description="Marcos [{name,date?,items?}] ou strings (opcional)."),
            },
            required=["version"],
        ),
    ),
    "generate_acceptance_criteria": _meta(
        "generate_acceptance_criteria",
        "artifact:generate",
        "artifact",
        "product-manager",
        "Gera critérios de aceite em Gherkin determinísticos a partir da user story e regras.",
        _schema(
            {
                "story": dict(_OBJ, description="História {role,goal,benefit?}."),
                "rules": dict(
                    _ARR,
                    description="Regras [{scenario?,given,when,then}] ou strings (opcional).",
                ),
            },
            required=["story"],
        ),
    ),
    "calculate_rice_score": _meta(
        "calculate_rice_score",
        "artifact:generate",
        "artifact",
        "product-manager",
        "Calcula o score RICE = (reach × impact × confidence) / effort de forma determinística.",
        _schema(
            {
                "reach": dict(_NUM, description="Alcance (nº de pessoas/eventos por período)."),
                "impact": dict(_NUM, description="Impacto (peso por pessoa)."),
                "confidence": dict(_NUM, description="Confiança (ex.: 0-100 ou 0-1)."),
                "effort": dict(_NUM, description="Esforço (person-months; deve ser > 0)."),
            },
            required=["reach", "impact", "confidence", "effort"],
        ),
    ),
    "generate_handoff_to_architecture": _meta(
        "generate_handoff_to_architecture",
        "artifact:generate",
        "artifact",
        "product-manager",
        "Gera um documento de handoff para Arquitetura determinístico a partir da feature/requisitos.",
        _schema(
            {
                "feature": dict(_STR, description="Feature alvo do handoff."),
                "requirements": dict(_ARR, description="Requisitos a repassar (opcional)."),
            },
            required=["feature"],
        ),
    ),
    "generate_handoff_to_design": _meta(
        "generate_handoff_to_design",
        "artifact:generate",
        "artifact",
        "product-manager",
        "Gera um documento de handoff para Design determinístico a partir da feature/fluxos.",
        _schema(
            {
                "feature": dict(_STR, description="Feature alvo do handoff."),
                "flows": dict(_ARR, description="Fluxos/jornadas a repassar (opcional)."),
            },
            required=["feature"],
        ),
    ),
    "generate_handoff_to_engineering": _meta(
        "generate_handoff_to_engineering",
        "artifact:generate",
        "artifact",
        "product-manager",
        "Gera um documento de handoff para Engenharia determinístico a partir da feature/specs.",
        _schema(
            {
                "feature": dict(_STR, description="Feature alvo do handoff."),
                "specs": dict(_ARR, description="Especificações técnicas a repassar (opcional)."),
            },
            required=["feature"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: ProductManagerStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_release_plan":
        return generate_release_plan(args)
    if name == "generate_acceptance_criteria":
        return generate_acceptance_criteria(args)
    if name == "calculate_rice_score":
        return calculate_rice_score(args)
    if name == "generate_handoff_to_architecture":
        return generate_handoff_to_architecture(args)
    if name == "generate_handoff_to_design":
        return generate_handoff_to_design(args)
    if name == "generate_handoff_to_engineering":
        return generate_handoff_to_engineering(args)
    # ── Feature Specs ──────────────────────────────────────────────────────── #
    if name == "save_feature_spec":
        return await save_feature_spec(
            store,
            feature=args["feature"],
            content=args["content"],
            objective=args.get("objective"),
            priority=args.get("priority"),
            status=args.get("status"),
        )
    if name == "list_feature_specs":
        return await list_feature_specs(store, feature=args.get("feature"), status=args.get("status"))
    if name == "get_feature_spec":
        return await get_feature_spec(store, spec_id=args["id"])
    if name == "update_feature_spec":
        return await update_feature_spec(
            store,
            spec_id=args["id"],
            objective=args.get("objective"),
            priority=args.get("priority"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_feature_spec":
        return await delete_feature_spec(store, spec_id=args["id"])
    # ── GTM Briefs ─────────────────────────────────────────────────────────── #
    if name == "save_gtm_brief":
        return await save_gtm_brief(
            store,
            product=args["product"],
            content=args["content"],
            launch_timing=args.get("launch_timing"),
            status=args.get("status"),
        )
    if name == "list_gtm_briefs":
        return await list_gtm_briefs(store, product=args.get("product"), status=args.get("status"))
    if name == "get_gtm_brief":
        return await get_gtm_brief(store, brief_id=args["id"])
    if name == "update_gtm_brief":
        return await update_gtm_brief(
            store,
            brief_id=args["id"],
            launch_timing=args.get("launch_timing"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_gtm_brief":
        return await delete_gtm_brief(store, brief_id=args["id"])
    # ── Release Plans ──────────────────────────────────────────────────────── #
    if name == "save_release_plan":
        return await save_release_plan(
            store,
            product=args["product"],
            content=args["content"],
            status=args.get("status"),
        )
    if name == "list_release_plans":
        return await list_release_plans(store, product=args.get("product"), status=args.get("status"))
    if name == "get_release_plan":
        return await get_release_plan(store, plan_id=args["id"])
    if name == "update_release_plan":
        return await update_release_plan(
            store,
            plan_id=args["id"],
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_release_plan":
        return await delete_release_plan(store, plan_id=args["id"])
    # ── Product Visions (upsert por product) ───────────────────────────────── #
    if name == "set_product_vision":
        return await set_product_vision(
            store,
            product=args["product"],
            vision=args.get("vision"),
            mission=args.get("mission"),
            goals=args.get("goals"),
            status=args.get("status"),
        )
    if name == "list_product_visions":
        return await list_product_visions(store, status=args.get("status"))
    if name == "get_product_vision":
        return await get_product_vision(store, product=args["product"])
    if name == "delete_product_vision":
        return await delete_product_vision(store, product=args["product"])
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            fmt=args.get("fmt"),
            meta=args.get("meta"),
        )
    if name == "list_artifacts":
        return await list_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_artifact":
        return await get_artifact(store, artifact_id=args["id"])
    if name == "delete_artifact":
        return await delete_artifact(store, artifact_id=args["id"])
    raise KeyError(name)
