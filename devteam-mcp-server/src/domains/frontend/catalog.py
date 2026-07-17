"""Catálogo de tools + dispatcher do domínio *frontend* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `frontend-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler, aqui renomeado ``dispatch``). O que ficou de
FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) —
isso é responsabilidade do AGREGADOR (`src/server/mcp_server.py`), compartilhado por
todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.frontend_<op>`` (namespace do server
    consolidado + nome de tool já prefixado pelo domínio — o gateway não deriva por
    nome, então a capability é o id estável).
  * ``required_scope`` passa a ``frontend:<recurso>:<ação>`` — PRESERVA o
    least-privilege por-tool do domínio (data_domain=frontend), só troca o antigo
    prefixo de namespace ``frontend-mcp`` pelo domínio canônico ``frontend``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_component``); o ``plugin.register()`` prefixa (``frontend_save_component``)
    e o ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim
    a lógica de roteamento copiada do server-fonte fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import FrontendStore
from .tools import (
    create_design_tokens,
    delete_artifact,
    delete_component,
    delete_form,
    delete_page,
    delete_story,
    generate_api_service,
    generate_component_variants,
    generate_custom_hook,
    generate_form_with_validation,
    generate_nextjs_page,
    generate_react_component,
    generate_storybook_story,
    generate_typescript_types,
    generate_wireframe,
    get_artifact,
    get_component,
    get_form,
    get_page,
    get_story,
    list_artifacts,
    list_components,
    list_forms,
    list_pages,
    list_stories,
    save_artifact,
    save_component,
    save_form,
    save_story,
    set_page,
    update_component,
    update_form,
    update_story,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "frontend"

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
    # ── Components ─────────────────────────────────────────────────────────── #
    "save_component": _meta(
        "save_component",
        "component:write",
        "component",
        "frontend",
        "Persiste um componente React fornecido pelo agente (o código vem do agente).",
        _schema(
            {
                "name": dict(_STR, description="Nome do componente."),
                "variant": dict(_STR, description="Variante (functional/class; default functional)."),
                "framework": dict(_STR, description="Framework (react/preact; opcional)."),
                "styling": dict(_STR, description="Estratégia de estilo (tailwind/css-modules; opcional)."),
                "props": dict(_OBJ, description="Props/interface do componente (opcional)."),
                "code": dict(_STR, description="Código-fonte gerado pelo agente (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_components": _meta(
        "list_components",
        "component:read",
        "component",
        "frontend",
        "Lista componentes persistidos, com filtros opcionais.",
        _schema(
            {
                "name": dict(_STR, description="Filtrar por nome (opcional)."),
                "framework": dict(_STR, description="Filtrar por framework (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_component": _meta(
        "get_component",
        "component:read",
        "component",
        "frontend",
        "Retorna um componente React persistido (código/props/variante/framework) por id.",
        _schema({"id": dict(_INT, description="Id do componente.")}, required=["id"]),
    ),
    "update_component": _meta(
        "update_component",
        "component:write",
        "component",
        "frontend",
        "Atualiza campos mutáveis de um componente (variant/framework/styling/props/code/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do componente."),
                "variant": dict(_STR, description="Nova variante (opcional)."),
                "framework": dict(_STR, description="Novo framework (opcional)."),
                "styling": dict(_STR, description="Nova estratégia de estilo (opcional)."),
                "props": dict(_OBJ, description="Novos props (opcional)."),
                "code": dict(_STR, description="Novo código-fonte (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_component": _meta(
        "delete_component",
        "component:write",
        "component",
        "frontend",
        "Remove (soft-delete) um componente React persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do componente.")}, required=["id"]),
    ),
    # ── Pages (upsert por route) ───────────────────────────────────────────── #
    "set_page": _meta(
        "set_page",
        "page:write",
        "page",
        "frontend",
        "Define (upsert) a página de uma rota com o código fornecido pelo agente.",
        _schema(
            {
                "route": dict(_STR, description="Rota da página (chave natural única)."),
                "title": dict(_STR, description="Título da página (opcional)."),
                "framework": dict(_STR, description="Framework (nextjs/remix; opcional)."),
                "page_type": dict(_STR, description="Tipo (app-route/pages-route; opcional)."),
                "code": dict(_STR, description="Código-fonte da página (opcional)."),
                "meta": dict(_OBJ, description="Metadados (layout/metadata/loaders; opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["route"],
        ),
    ),
    "list_pages": _meta(
        "list_pages",
        "page:read",
        "page",
        "frontend",
        "Lista páginas persistidas, com filtros opcionais.",
        _schema(
            {
                "framework": dict(_STR, description="Filtrar por framework (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_page": _meta(
        "get_page",
        "page:read",
        "page",
        "frontend",
        "Retorna a página persistida de uma rota (código/framework/meta) pela chave route.",
        _schema({"route": dict(_STR, description="Rota da página.")}, required=["route"]),
    ),
    "delete_page": _meta(
        "delete_page",
        "page:write",
        "page",
        "frontend",
        "Remove (soft-delete) a página persistida de uma rota pela chave route; idempotente.",
        _schema({"route": dict(_STR, description="Rota da página.")}, required=["route"]),
    ),
    # ── Forms ──────────────────────────────────────────────────────────────── #
    "save_form": _meta(
        "save_form",
        "form:write",
        "form",
        "frontend",
        "Persiste um formulário fornecido pelo agente (campos/código vêm do agente).",
        _schema(
            {
                "name": dict(_STR, description="Nome do formulário."),
                "library": dict(_STR, description="Biblioteca (react-hook-form/formik; opcional)."),
                "validation": dict(_STR, description="Validação (zod/yup; opcional)."),
                "fields": dict(_ARR, description="Campos + regras (opcional)."),
                "code": dict(_STR, description="Código-fonte gerado (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name"],
        ),
    ),
    "list_forms": _meta(
        "list_forms",
        "form:read",
        "form",
        "frontend",
        "Lista formulários persistidos, com filtros opcionais.",
        _schema(
            {
                "name": dict(_STR, description="Filtrar por nome (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_form": _meta(
        "get_form",
        "form:read",
        "form",
        "frontend",
        "Retorna um formulário persistido (campos/validação/biblioteca/código) por id.",
        _schema({"id": dict(_INT, description="Id do formulário.")}, required=["id"]),
    ),
    "update_form": _meta(
        "update_form",
        "form:write",
        "form",
        "frontend",
        "Atualiza campos mutáveis de um formulário.",
        _schema(
            {
                "id": dict(_INT, description="Id do formulário."),
                "library": dict(_STR, description="Nova biblioteca (opcional)."),
                "validation": dict(_STR, description="Nova validação (opcional)."),
                "fields": dict(_ARR, description="Novos campos (opcional)."),
                "code": dict(_STR, description="Novo código-fonte (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_form": _meta(
        "delete_form",
        "form:write",
        "form",
        "frontend",
        "Remove (soft-delete) um formulário persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do formulário.")}, required=["id"]),
    ),
    # ── Stories ────────────────────────────────────────────────────────────── #
    "save_story": _meta(
        "save_story",
        "story:write",
        "story",
        "frontend",
        "Persiste uma story de Storybook fornecida pelo agente (código/estados vêm do agente).",
        _schema(
            {
                "component": dict(_STR, description="Componente-alvo da story."),
                "title": dict(_STR, description="Título da story (opcional)."),
                "framework": dict(_STR, description="Framework (storybook/csf; opcional)."),
                "stories": dict(_ARR, description="Lista de estados/stories (opcional)."),
                "code": dict(_STR, description="Código-fonte gerado (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["component"],
        ),
    ),
    "list_stories": _meta(
        "list_stories",
        "story:read",
        "story",
        "frontend",
        "Lista stories persistidas, com filtros opcionais.",
        _schema(
            {
                "component": dict(_STR, description="Filtrar por componente (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_story": _meta(
        "get_story",
        "story:read",
        "story",
        "frontend",
        "Retorna uma story de Storybook persistida (estados/framework/código) por id.",
        _schema({"id": dict(_INT, description="Id da story.")}, required=["id"]),
    ),
    "update_story": _meta(
        "update_story",
        "story:write",
        "story",
        "frontend",
        "Atualiza campos mutáveis de uma story de Storybook por id (título/framework/stories/código/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da story."),
                "title": dict(_STR, description="Novo título (opcional)."),
                "framework": dict(_STR, description="Novo framework (opcional)."),
                "stories": dict(_ARR, description="Novos estados/stories (opcional)."),
                "code": dict(_STR, description="Novo código-fonte (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_story": _meta(
        "delete_story",
        "story:write",
        "story",
        "frontend",
        "Remove (soft-delete) uma story de Storybook persistida por id; idempotente.",
        _schema({"id": dict(_INT, description="Id da story.")}, required=["id"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "frontend",
        "Persiste um artefato de UI (código/scaffold) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: react_component|nextjs_page|form|storybook_story|hook|"
                        "layout|context|style|util|api_client."
                    ),
                ),
                "target": dict(_STR, description="Alvo (componente/rota/módulo)."),
                "content": dict(_STR, description="Código/scaffold gerado pelo agente."),
                "framework": dict(_STR, description="Framework (opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "frontend",
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
        "frontend",
        "Retorna um artefato de UI persistido (código/scaffold gerado pelo agente) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "frontend",
        "Remove (soft-delete) um artefato de UI persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes stateful seguem `<resource_type>:<acao>` com :read
    # p/ consultas e :write p/ mutações do estado do tenant. Geradores não LEEM nem
    # GRAVAM estado — só computam scaffold de UI — então nem :read nem :write cabem.
    # Escolha: nova ação `:generate` sobre o resource_type do domínio scaffoldado
    # (component/page/form/story ou o catch-all `artifact` p/ hook/types/api/etc.):
    # least-privilege real (um token só de geração não abre leitura/escrita do estado
    # persistido daquele recurso). data_domain=frontend.
    "generate_react_component": _meta(
        "generate_react_component",
        "component:generate",
        "component",
        "frontend",
        "Gera um componente React (TSX) determinístico a partir de name/props/hooks.",
        _schema(
            {
                "name": dict(_STR, description="Nome do componente."),
                "props": dict(_ARR, description="Props: nomes ou [{name,type?,optional?}] (opcional)."),
                "hooks": dict(_ARR, description="Hooks a incluir (ex.: useState, useEffect; opcional)."),
            },
            required=["name"],
        ),
    ),
    "generate_nextjs_page": _meta(
        "generate_nextjs_page",
        "page:generate",
        "page",
        "frontend",
        "Gera uma página Next.js (app router) determinística a partir de route/title/sections.",
        _schema(
            {
                "route": dict(_STR, description="Rota da página (ex.: /dashboard)."),
                "title": dict(_STR, description="Título/metadata (derivado da rota se ausente)."),
                "sections": dict(_ARR, description="Seções a esboçar na página (opcional)."),
            },
            required=["route"],
        ),
    ),
    "generate_custom_hook": _meta(
        "generate_custom_hook",
        "artifact:generate",
        "artifact",
        "frontend",
        "Gera um custom hook React (TS) determinístico a partir de name/params/returns.",
        _schema(
            {
                "name": dict(_STR, description="Nome do hook (deve começar com 'use')."),
                "params": dict(_ARR, description="Parâmetros: nomes ou [{name,type?}] (opcional)."),
                "returns": dict(_STR, description="Tipo de retorno TS (default 'void')."),
            },
            required=["name"],
        ),
    ),
    "generate_form_with_validation": _meta(
        "generate_form_with_validation",
        "form:generate",
        "form",
        "frontend",
        "Gera um formulário react-hook-form + zod determinístico a partir dos campos e regras.",
        _schema(
            {
                "name": dict(_STR, description="Nome do formulário."),
                "fields": dict(
                    _ARR,
                    description="Campos [{name,type?,rules?}] (rules: required|email|url|min:N|max:N).",
                ),
            },
            required=["name", "fields"],
        ),
    ),
    "generate_typescript_types": _meta(
        "generate_typescript_types",
        "artifact:generate",
        "artifact",
        "frontend",
        "Gera uma interface TypeScript determinística a partir de name/fields.",
        _schema(
            {
                "name": dict(_STR, description="Nome da interface."),
                "fields": dict(_ARR, description="Campos [{name,type?,optional?}]."),
            },
            required=["name", "fields"],
        ),
    ),
    "generate_storybook_story": _meta(
        "generate_storybook_story",
        "story:generate",
        "story",
        "frontend",
        "Gera uma story do Storybook (CSF3) determinística a partir do componente e variantes.",
        _schema(
            {
                "component": dict(_STR, description="Componente-alvo da story."),
                "variants": dict(_ARR, description="Variantes: nomes ou [{name,args?}] (opcional)."),
            },
            required=["component"],
        ),
    ),
    "generate_api_service": _meta(
        "generate_api_service",
        "artifact:generate",
        "artifact",
        "frontend",
        "Gera um cliente de API (fetch TS) determinístico a partir de base/endpoints.",
        _schema(
            {
                "base": dict(_STR, description="Base URL do serviço."),
                "endpoints": dict(_ARR, description="Endpoints [{name,method?,path?}]."),
            },
            required=["base", "endpoints"],
        ),
    ),
    "generate_component_variants": _meta(
        "generate_component_variants",
        "component:generate",
        "component",
        "frontend",
        "Gera um mapa de variantes (class-variance-authority) determinístico a partir de base/variants.",
        _schema(
            {
                "base": dict(_STR, description="Nome/classe base do componente."),
                "variants": dict(_ARR, description="Variantes: nomes ou [{name,classes?}]."),
            },
            required=["base", "variants"],
        ),
    ),
    "generate_wireframe": _meta(
        "generate_wireframe",
        "artifact:generate",
        "artifact",
        "frontend",
        "Gera um wireframe ASCII determinístico a partir de title/blocks.",
        _schema(
            {
                "title": dict(_STR, description="Título do wireframe."),
                "blocks": dict(_ARR, description="Blocos: nomes ou [{name,height?}]."),
                "width": dict(_INT, description="Largura do quadro (default 44)."),
            },
            required=["title", "blocks"],
        ),
    ),
    "create_design_tokens": _meta(
        "create_design_tokens",
        "artifact:generate",
        "artifact",
        "frontend",
        "Gera design tokens (CSS custom properties + JSON) determinísticos a partir de palette/spacing.",
        _schema(
            {
                "palette": dict(_OBJ, description="Paleta {nome: cor} (ex.: {primary: '#0055ff'})."),
                "spacing": dict(_OBJ, description="Escala de espaçamento {nome: valor} (default sm/md/lg)."),
            },
            required=["palette"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: FrontendStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). ``name`` é o nome de op SEM prefixo de
    domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_react_component":
        return generate_react_component(args)
    if name == "generate_nextjs_page":
        return generate_nextjs_page(args)
    if name == "generate_custom_hook":
        return generate_custom_hook(args)
    if name == "generate_form_with_validation":
        return generate_form_with_validation(args)
    if name == "generate_typescript_types":
        return generate_typescript_types(args)
    if name == "generate_storybook_story":
        return generate_storybook_story(args)
    if name == "generate_api_service":
        return generate_api_service(args)
    if name == "generate_component_variants":
        return generate_component_variants(args)
    if name == "generate_wireframe":
        return generate_wireframe(args)
    if name == "create_design_tokens":
        return create_design_tokens(args)
    # ── Components ─────────────────────────────────────────────────────────── #
    if name == "save_component":
        return await save_component(
            store,
            name=args["name"],
            variant=args.get("variant", "functional"),
            framework=args.get("framework"),
            styling=args.get("styling"),
            props=args.get("props"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "list_components":
        return await list_components(
            store,
            name=args.get("name"),
            framework=args.get("framework"),
            status=args.get("status"),
        )
    if name == "get_component":
        return await get_component(store, component_id=args["id"])
    if name == "update_component":
        return await update_component(
            store,
            component_id=args["id"],
            variant=args.get("variant"),
            framework=args.get("framework"),
            styling=args.get("styling"),
            props=args.get("props"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "delete_component":
        return await delete_component(store, component_id=args["id"])
    # ── Pages (upsert por route) ───────────────────────────────────────────── #
    if name == "set_page":
        return await set_page(
            store,
            route=args["route"],
            title=args.get("title"),
            framework=args.get("framework"),
            page_type=args.get("page_type"),
            code=args.get("code"),
            meta=args.get("meta"),
            status=args.get("status"),
        )
    if name == "list_pages":
        return await list_pages(store, framework=args.get("framework"), status=args.get("status"))
    if name == "get_page":
        return await get_page(store, route=args["route"])
    if name == "delete_page":
        return await delete_page(store, route=args["route"])
    # ── Forms ──────────────────────────────────────────────────────────────── #
    if name == "save_form":
        return await save_form(
            store,
            name=args["name"],
            library=args.get("library"),
            validation=args.get("validation"),
            fields=args.get("fields"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "list_forms":
        return await list_forms(store, name=args.get("name"), status=args.get("status"))
    if name == "get_form":
        return await get_form(store, form_id=args["id"])
    if name == "update_form":
        return await update_form(
            store,
            form_id=args["id"],
            library=args.get("library"),
            validation=args.get("validation"),
            fields=args.get("fields"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "delete_form":
        return await delete_form(store, form_id=args["id"])
    # ── Stories ────────────────────────────────────────────────────────────── #
    if name == "save_story":
        return await save_story(
            store,
            component=args["component"],
            title=args.get("title"),
            framework=args.get("framework"),
            stories=args.get("stories"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "list_stories":
        return await list_stories(store, component=args.get("component"), status=args.get("status"))
    if name == "get_story":
        return await get_story(store, story_id=args["id"])
    if name == "update_story":
        return await update_story(
            store,
            story_id=args["id"],
            title=args.get("title"),
            framework=args.get("framework"),
            stories=args.get("stories"),
            code=args.get("code"),
            status=args.get("status"),
        )
    if name == "delete_story":
        return await delete_story(store, story_id=args["id"])
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            framework=args.get("framework"),
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
