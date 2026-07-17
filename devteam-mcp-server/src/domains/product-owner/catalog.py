"""Catálogo de tools + dispatcher do domínio *product-owner* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `product-owner-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler, aqui renomeado ``dispatch``). O que ficou de FORA
é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) — isso é
responsabilidade do AGREGADOR (`src/server/mcp_server.py`), compartilhado por todos os
domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.product-owner_<op>`` (namespace do server
    consolidado + nome de tool já prefixado pelo domínio — o gateway não deriva por
    nome, então a capability é o id estável).
  * ``required_scope`` passa a ``product-owner:<recurso>:<ação>`` — PRESERVA o
    least-privilege por-tool do domínio (data_domain=product-owner), só troca o antigo
    prefixo de namespace ``product-owner-mcp`` pelo domínio canônico ``product-owner``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_user_story``); o ``plugin.register()`` prefixa (``product-owner_save_user_story``)
    e o ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim
    a lógica de roteamento copiada do server-fonte fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import ProductOwnerStore
from .tools import (
    delete_backlog_item,
    delete_mvp_scope,
    delete_po_artifact,
    delete_product_vision,
    delete_user_persona,
    delete_user_story,
    generate_epic,
    generate_feature_breakdown,
    generate_homologation_checklist,
    generate_jira_tasks,
    generate_release_notes,
    generate_user_stories,
    get_backlog_item,
    get_mvp_scope,
    get_po_artifact,
    get_product_vision,
    get_user_persona,
    get_user_story,
    list_backlog_items,
    list_mvp_scopes,
    list_po_artifacts,
    list_product_visions,
    list_user_personas,
    list_user_stories,
    save_backlog_item,
    save_po_artifact,
    save_user_persona,
    save_user_story,
    set_mvp_scope,
    set_product_vision,
    update_backlog_item,
    update_user_persona,
    update_user_story,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "product-owner"

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
    # ── User Stories ───────────────────────────────────────────────────────── #
    "save_user_story": _meta(
        "save_user_story",
        "user_story:write",
        "user_story",
        "product-owner",
        "Persiste uma user story fornecida pelo agente (o conteúdo vem do agente).",
        _schema(
            {
                "feature": dict(_STR, description="Feature/épico alvo."),
                "role": dict(_STR, description="Papel/persona da história."),
                "goal": dict(_STR, description="Objetivo/ação desejada (opcional)."),
                "benefit": dict(_STR, description="Benefício/valor esperado (opcional)."),
                "story": dict(_STR, description="Sentença 'As a ... I want ... so that ...' (opcional)."),
                "acceptance_criteria": dict(_ARR, description="Critérios de aceite (lista, opcional)."),
                "priority": dict(_STR, description="Prioridade (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["feature", "role"],
        ),
    ),
    "list_user_stories": _meta(
        "list_user_stories",
        "user_story:read",
        "user_story",
        "product-owner",
        "Lista user stories persistidas, com filtros opcionais.",
        _schema(
            {
                "feature": dict(_STR, description="Filtrar por feature (opcional)."),
                "role": dict(_STR, description="Filtrar por papel (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_user_story": _meta(
        "get_user_story",
        "user_story:read",
        "user_story",
        "product-owner",
        "Retorna uma user story persistida (papel, objetivo, benefício, critérios de aceite) por id.",
        _schema({"id": dict(_INT, description="Id da história.")}, required=["id"]),
    ),
    "update_user_story": _meta(
        "update_user_story",
        "user_story:write",
        "user_story",
        "product-owner",
        "Atualiza campos mutáveis de uma user story.",
        _schema(
            {
                "id": dict(_INT, description="Id da história."),
                "role": dict(_STR, description="Novo papel (opcional)."),
                "goal": dict(_STR, description="Novo objetivo (opcional)."),
                "benefit": dict(_STR, description="Novo benefício (opcional)."),
                "story": dict(_STR, description="Nova sentença (opcional)."),
                "acceptance_criteria": dict(_ARR, description="Novos critérios de aceite (opcional)."),
                "priority": dict(_STR, description="Nova prioridade (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_user_story": _meta(
        "delete_user_story",
        "user_story:write",
        "user_story",
        "product-owner",
        "Remove (soft-delete) uma user story persistida por id; informa deleted e deleted_count.",
        _schema({"id": dict(_INT, description="Id da história.")}, required=["id"]),
    ),
    # ── MVP Scopes (upsert por product) ────────────────────────────────────── #
    "set_mvp_scope": _meta(
        "set_mvp_scope",
        "mvp_scope:write",
        "mvp_scope",
        "product-owner",
        "Define (upsert) o escopo de MVP de um produto com o recorte fornecido.",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo (chave natural única)."),
                "content": dict(_OBJ, description="Recorte do MVP (core/should/could/out_of_scope)."),
                "goal": dict(_STR, description="Objetivo do MVP (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["product", "content"],
        ),
    ),
    "list_mvp_scopes": _meta(
        "list_mvp_scopes",
        "mvp_scope:read",
        "mvp_scope",
        "product-owner",
        "Lista escopos de MVP persistidos, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_mvp_scope": _meta(
        "get_mvp_scope",
        "mvp_scope:read",
        "mvp_scope",
        "product-owner",
        (
            "Retorna o escopo de MVP persistido (core/should/could/out_of_scope) de um produto "
            "pela chave product."
        ),
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    "delete_mvp_scope": _meta(
        "delete_mvp_scope",
        "mvp_scope:write",
        "mvp_scope",
        "product-owner",
        "Soft-delete do escopo de MVP de um produto.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    # ── Product Visions (upsert por product) ───────────────────────────────── #
    "set_product_vision": _meta(
        "set_product_vision",
        "product_vision:write",
        "product_vision",
        "product-owner",
        "Define (upsert) a visão de um produto com o conteúdo fornecido.",
        _schema(
            {
                "product": dict(_STR, description="Produto alvo (chave natural única)."),
                "vision": dict(_STR, description="Sentença de visão (opcional)."),
                "target_audience": dict(_STR, description="Público-alvo (opcional)."),
                "content": dict(
                    _OBJ, description="Conteúdo da visão (mission/goals/success_criteria/differentiator)."
                ),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["product"],
        ),
    ),
    "list_product_visions": _meta(
        "list_product_visions",
        "product_vision:read",
        "product_vision",
        "product-owner",
        "Lista visões de produto persistidas, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_product_vision": _meta(
        "get_product_vision",
        "product_vision:read",
        "product_vision",
        "product-owner",
        "Retorna a visão de produto persistida (missão, metas, público-alvo) pela chave natural product.",
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    "delete_product_vision": _meta(
        "delete_product_vision",
        "product_vision:write",
        "product_vision",
        "product-owner",
        (
            "Remove (soft-delete) a visão de um produto pela chave natural product; "
            "informa deleted e deleted_count."
        ),
        _schema({"product": dict(_STR, description="Produto alvo.")}, required=["product"]),
    ),
    # ── User Personas ──────────────────────────────────────────────────────── #
    "save_user_persona": _meta(
        "save_user_persona",
        "user_persona:write",
        "user_persona",
        "product-owner",
        "Persiste uma persona de usuário fornecida pelo agente.",
        _schema(
            {
                "name": dict(_STR, description="Nome da persona."),
                "segment": dict(_STR, description="Segmento (opcional)."),
                "demographics": dict(_OBJ, description="Mapa demográfico (opcional)."),
                "goals": dict(_ARR, description="Objetivos (lista, opcional)."),
                "pains": dict(_ARR, description="Dores (lista, opcional)."),
                "behaviors": dict(_ARR, description="Comportamentos (lista, opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_user_personas": _meta(
        "list_user_personas",
        "user_persona:read",
        "user_persona",
        "product-owner",
        "Lista personas persistidas, com filtros opcionais.",
        _schema(
            {
                "segment": dict(_STR, description="Filtrar por segmento (opcional)."),
                "name": dict(_STR, description="Filtrar por nome (opcional)."),
            }
        ),
    ),
    "get_user_persona": _meta(
        "get_user_persona",
        "user_persona:read",
        "user_persona",
        "product-owner",
        "Retorna uma persona de usuário persistida (segmento, objetivos, dores, comportamentos) por id.",
        _schema({"id": dict(_INT, description="Id da persona.")}, required=["id"]),
    ),
    "update_user_persona": _meta(
        "update_user_persona",
        "user_persona:write",
        "user_persona",
        "product-owner",
        "Atualiza campos mutáveis de uma persona.",
        _schema(
            {
                "id": dict(_INT, description="Id da persona."),
                "segment": dict(_STR, description="Novo segmento (opcional)."),
                "demographics": dict(_OBJ, description="Novo mapa demográfico (opcional)."),
                "goals": dict(_ARR, description="Novos objetivos (opcional)."),
                "pains": dict(_ARR, description="Novas dores (opcional)."),
                "behaviors": dict(_ARR, description="Novos comportamentos (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_user_persona": _meta(
        "delete_user_persona",
        "user_persona:write",
        "user_persona",
        "product-owner",
        "Remove (soft-delete) uma persona de usuário persistida por id; informa deleted e deleted_count.",
        _schema({"id": dict(_INT, description="Id da persona.")}, required=["id"]),
    ),
    # ── Backlog Items (score RICE determinístico dobrado no save) ──────────── #
    "save_backlog_item": _meta(
        "save_backlog_item",
        "backlog_item:write",
        "backlog_item",
        "product-owner",
        "Persiste um item de backlog. Se score não vier e os campos RICE existirem, calcula-o.",
        _schema(
            {
                "name": dict(_STR, description="Nome/título do item."),
                "framework": dict(_STR, description="Framework (RICE/ICE/MoSCoW; default RICE)."),
                "reach": dict(_NUM, description="Alcance RICE (opcional)."),
                "impact": dict(_NUM, description="Impacto RICE (opcional)."),
                "confidence": dict(_NUM, description="Confiança RICE 0-1 ou 1-100 (opcional)."),
                "effort": dict(_NUM, description="Esforço RICE (opcional)."),
                "score": dict(_NUM, description="Score (opcional; calculado se ausente)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_backlog_items": _meta(
        "list_backlog_items",
        "backlog_item:read",
        "backlog_item",
        "product-owner",
        "Lista itens de backlog persistidos (ordenados por score desc), com filtros opcionais.",
        _schema(
            {
                "framework": dict(_STR, description="Filtrar por framework (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_backlog_item": _meta(
        "get_backlog_item",
        "backlog_item:read",
        "backlog_item",
        "product-owner",
        "Retorna um item de backlog persistido (framework, componentes RICE, score, status) por id.",
        _schema({"id": dict(_INT, description="Id do item.")}, required=["id"]),
    ),
    "update_backlog_item": _meta(
        "update_backlog_item",
        "backlog_item:write",
        "backlog_item",
        "product-owner",
        "Atualiza campos mutáveis de um item de backlog.",
        _schema(
            {
                "id": dict(_INT, description="Id do item."),
                "framework": dict(_STR, description="Novo framework (opcional)."),
                "reach": dict(_NUM, description="Novo alcance (opcional)."),
                "impact": dict(_NUM, description="Novo impacto (opcional)."),
                "confidence": dict(_NUM, description="Nova confiança (opcional)."),
                "effort": dict(_NUM, description="Novo esforço (opcional)."),
                "score": dict(_NUM, description="Novo score (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_backlog_item": _meta(
        "delete_backlog_item",
        "backlog_item:write",
        "backlog_item",
        "product-owner",
        "Soft-delete de um item de backlog por id.",
        _schema({"id": dict(_INT, description="Id do item.")}, required=["id"]),
    ),
    # ── PO Artifacts (histórico append-only) ───────────────────────────────── #
    "save_po_artifact": _meta(
        "save_po_artifact",
        "artifact:write",
        "artifact",
        "product-owner",
        "Persiste um artefato de PO (estruturado) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: journey|risks|handoff_architecture|handoff_design|"
                        "handoff_engineering|discovery|gtm|release|feature_spec|metrics|problem."
                    ),
                ),
                "target": dict(_STR, description="Alvo (feature/product/persona)."),
                "content": dict(_OBJ, description="Artefato estruturado gerado pelo agente."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target"],
        ),
    ),
    "list_po_artifacts": _meta(
        "list_po_artifacts",
        "artifact:read",
        "artifact",
        "product-owner",
        "Lista artefatos de PO persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_po_artifact": _meta(
        "get_po_artifact",
        "artifact:read",
        "artifact",
        "product-owner",
        "Retorna um artefato de PO persistido (journey/handoff/discovery/release etc.) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_po_artifact": _meta(
        "delete_po_artifact",
        "artifact:write",
        "artifact",
        "product-owner",
        "Soft-delete de um artefato de PO por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com :read
    # p/ consultas e :write p/ mutações do estado do tenant. Geradores não LEEM nem
    # GRAVAM estado — só FORMATAM a spec em artefatos de PO — então nenhum dos dois
    # cabe. Escolha: nova ação `:generate` sobre resource_type=`artifact` (o mesmo
    # domínio dos artefatos de PO produzidos): least-privilege real (um token só de
    # geração não abre leitura/escrita de artefatos persistidos). data_domain=product-owner.
    "generate_epic": _meta(
        "generate_epic",
        "artifact:generate",
        "artifact",
        "product-owner",
        "Formata um épico em markdown (objetivo + user stories) determinístico a partir da spec.",
        _schema(
            {
                "title": dict(_STR, description="Título do épico."),
                "goal": dict(_STR, description="Objetivo do épico (opcional)."),
                "stories": dict(_ARR, description="User stories (strings ou {story/title/name}; opcional)."),
            },
            required=["title"],
        ),
    ),
    "generate_feature_breakdown": _meta(
        "generate_feature_breakdown",
        "artifact:generate",
        "artifact",
        "product-owner",
        "Formata o breakdown de uma feature em markdown estruturado (partes + itens) determinístico.",
        _schema(
            {
                "feature": dict(_STR, description="Feature alvo."),
                "parts": dict(_ARR, description="Partes (strings ou {name, items[]}; opcional)."),
            },
            required=["feature"],
        ),
    ),
    "generate_jira_tasks": _meta(
        "generate_jira_tasks",
        "artifact:generate",
        "artifact",
        "product-owner",
        "Formata uma lista de tasks de Jira estruturada (chaves sequenciais) a partir do breakdown.",
        _schema(
            {
                "breakdown": dict(
                    _ARR, description="Itens do breakdown (strings ou {summary/name,type?,description?})."
                ),
                "project": dict(_STR, description="Prefixo da chave das tasks (default 'TASK')."),
            },
            required=["breakdown"],
        ),
    ),
    "generate_release_notes": _meta(
        "generate_release_notes",
        "artifact:generate",
        "artifact",
        "product-owner",
        "Formata release notes em markdown (mudanças agrupadas por tipo) determinístico.",
        _schema(
            {
                "version": dict(_STR, description="Versão do release."),
                "changes": dict(_ARR, description="Mudanças [{type,desc}] (strings ou dicts; opcional)."),
            },
            required=["version"],
        ),
    ),
    "generate_user_stories": _meta(
        "generate_user_stories",
        "artifact:generate",
        "artifact",
        "product-owner",
        "Formata uma user story markdown 'Como... quero... para...' com critérios de aceite.",
        _schema(
            {
                "role": dict(_STR, description="Papel/persona ('Como ...')."),
                "goal": dict(_STR, description="Objetivo/ação ('quero ...')."),
                "benefit": dict(_STR, description="Benefício ('para ...'; opcional)."),
                "criteria": dict(_ARR, description="Critérios de aceite (strings ou dicts; opcional)."),
            },
            required=["role", "goal"],
        ),
    ),
    "generate_homologation_checklist": _meta(
        "generate_homologation_checklist",
        "artifact:generate",
        "artifact",
        "product-owner",
        "Formata um checklist de homologação em markdown (caixas de verificação) determinístico.",
        _schema(
            {
                "items": dict(_ARR, description="Itens do checklist (strings ou {label/name/title})."),
                "title": dict(_STR, description="Título do checklist (default 'Homologação')."),
            },
            required=["items"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: ProductOwnerStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). ``name`` é o nome de op SEM prefixo de
    domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_epic":
        return generate_epic(args)
    if name == "generate_feature_breakdown":
        return generate_feature_breakdown(args)
    if name == "generate_jira_tasks":
        return generate_jira_tasks(args)
    if name == "generate_release_notes":
        return generate_release_notes(args)
    if name == "generate_user_stories":
        return generate_user_stories(args)
    if name == "generate_homologation_checklist":
        return generate_homologation_checklist(args)
    # ── User Stories ───────────────────────────────────────────────────────── #
    if name == "save_user_story":
        return await save_user_story(
            store,
            feature=args["feature"],
            role=args["role"],
            goal=args.get("goal"),
            benefit=args.get("benefit"),
            story=args.get("story"),
            acceptance_criteria=args.get("acceptance_criteria"),
            priority=args.get("priority"),
            status=args.get("status"),
        )
    if name == "list_user_stories":
        return await list_user_stories(
            store, feature=args.get("feature"), role=args.get("role"), status=args.get("status")
        )
    if name == "get_user_story":
        return await get_user_story(store, story_id=args["id"])
    if name == "update_user_story":
        return await update_user_story(
            store,
            story_id=args["id"],
            role=args.get("role"),
            goal=args.get("goal"),
            benefit=args.get("benefit"),
            story=args.get("story"),
            acceptance_criteria=args.get("acceptance_criteria"),
            priority=args.get("priority"),
            status=args.get("status"),
        )
    if name == "delete_user_story":
        return await delete_user_story(store, story_id=args["id"])
    # ── MVP Scopes ─────────────────────────────────────────────────────────── #
    if name == "set_mvp_scope":
        return await set_mvp_scope(
            store,
            product=args["product"],
            content=args["content"],
            goal=args.get("goal"),
            status=args.get("status"),
        )
    if name == "list_mvp_scopes":
        return await list_mvp_scopes(store, status=args.get("status"))
    if name == "get_mvp_scope":
        return await get_mvp_scope(store, product=args["product"])
    if name == "delete_mvp_scope":
        return await delete_mvp_scope(store, product=args["product"])
    # ── Product Visions ────────────────────────────────────────────────────── #
    if name == "set_product_vision":
        return await set_product_vision(
            store,
            product=args["product"],
            vision=args.get("vision"),
            target_audience=args.get("target_audience"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "list_product_visions":
        return await list_product_visions(store, status=args.get("status"))
    if name == "get_product_vision":
        return await get_product_vision(store, product=args["product"])
    if name == "delete_product_vision":
        return await delete_product_vision(store, product=args["product"])
    # ── User Personas ──────────────────────────────────────────────────────── #
    if name == "save_user_persona":
        return await save_user_persona(
            store,
            name=args["name"],
            segment=args.get("segment"),
            demographics=args.get("demographics"),
            goals=args.get("goals"),
            pains=args.get("pains"),
            behaviors=args.get("behaviors"),
        )
    if name == "list_user_personas":
        return await list_user_personas(store, segment=args.get("segment"), name=args.get("name"))
    if name == "get_user_persona":
        return await get_user_persona(store, persona_id=args["id"])
    if name == "update_user_persona":
        return await update_user_persona(
            store,
            persona_id=args["id"],
            segment=args.get("segment"),
            demographics=args.get("demographics"),
            goals=args.get("goals"),
            pains=args.get("pains"),
            behaviors=args.get("behaviors"),
        )
    if name == "delete_user_persona":
        return await delete_user_persona(store, persona_id=args["id"])
    # ── Backlog Items ──────────────────────────────────────────────────────── #
    if name == "save_backlog_item":
        return await save_backlog_item(
            store,
            name=args["name"],
            framework=args.get("framework", "RICE"),
            reach=args.get("reach"),
            impact=args.get("impact"),
            confidence=args.get("confidence"),
            effort=args.get("effort"),
            score=args.get("score"),
            status=args.get("status"),
        )
    if name == "list_backlog_items":
        return await list_backlog_items(store, framework=args.get("framework"), status=args.get("status"))
    if name == "get_backlog_item":
        return await get_backlog_item(store, item_id=args["id"])
    if name == "update_backlog_item":
        return await update_backlog_item(
            store,
            item_id=args["id"],
            framework=args.get("framework"),
            reach=args.get("reach"),
            impact=args.get("impact"),
            confidence=args.get("confidence"),
            effort=args.get("effort"),
            score=args.get("score"),
            status=args.get("status"),
        )
    if name == "delete_backlog_item":
        return await delete_backlog_item(store, item_id=args["id"])
    # ── PO Artifacts ───────────────────────────────────────────────────────── #
    if name == "save_po_artifact":
        return await save_po_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args.get("content"),
            meta=args.get("meta"),
        )
    if name == "list_po_artifacts":
        return await list_po_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_po_artifact":
        return await get_po_artifact(store, artifact_id=args["id"])
    if name == "delete_po_artifact":
        return await delete_po_artifact(store, artifact_id=args["id"])
    raise KeyError(name)
