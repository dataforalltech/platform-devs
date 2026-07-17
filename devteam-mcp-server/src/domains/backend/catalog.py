"""Catálogo de tools + dispatcher do domínio *backend* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `backend-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler, aqui renomeado ``dispatch``). O que ficou de
FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) — isso
é responsabilidade do AGREGADOR (`src/server/mcp_server.py`), compartilhado por todos os
domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.backend_<op>`` (namespace do server
    consolidado + nome de tool já prefixado pelo domínio — o gateway não deriva por
    nome, então a capability é o id estável).
  * ``required_scope`` passa a ``backend:<recurso>:<ação>`` — PRESERVA o
    least-privilege por-tool do domínio (data_domain=backend/security), só troca o antigo
    prefixo de namespace ``backend-mcp`` pelo domínio canônico ``backend``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_api_contract``); o ``plugin.register()`` prefixa (``backend_save_api_contract``)
    e o ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim
    a lógica de roteamento copiada do server-fonte fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import BackendStore
from .tools import (
    delete_api_contract,
    delete_artifact,
    delete_auth_policy,
    delete_code_review,
    delete_database_schema,
    generate_api_contract,
    generate_auth_policy,
    generate_database_schema,
    generate_event_contracts,
    generate_fastapi_router,
    generate_migration,
    generate_repository_layer,
    generate_service_layer,
    get_api_contract,
    get_artifact,
    get_auth_policy,
    get_code_review,
    get_database_schema,
    list_api_contracts,
    list_artifacts,
    list_auth_policies,
    list_code_reviews,
    list_database_schemas,
    save_api_contract,
    save_artifact,
    save_auth_policy,
    save_code_review,
    save_database_schema,
    update_database_schema,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "backend"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <domain>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consultas (list/get) usam :read;
# mutações (save/update/delete) usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}


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
    # ── API Contracts (upsert por endpoint+method) ─────────────────────────── #
    "save_api_contract": _meta(
        "save_api_contract",
        "api_contract:write",
        "api_contract",
        "backend",
        "Persiste (upsert) um contrato de API fornecido pelo agente (chave: endpoint+method).",
        _schema(
            {
                "endpoint": dict(_STR, description="Path do endpoint (chave natural)."),
                "method": dict(_STR, description="Método HTTP (chave natural; GET/POST/...)."),
                "description": dict(_STR, description="Descrição do endpoint (opcional)."),
                "request_schema": dict(_OBJ, description="Schema da request (opcional)."),
                "response_schema": dict(_OBJ, description="Schema da response (opcional)."),
                "status_codes": dict(_ARR, description="Status codes suportados (opcional)."),
                "status": dict(_STR, description="Status do contrato (opcional)."),
            },
            required=["endpoint", "method"],
        ),
    ),
    "list_api_contracts": _meta(
        "list_api_contracts",
        "api_contract:read",
        "api_contract",
        "backend",
        "Lista contratos de API persistidos, com filtros opcionais.",
        _schema(
            {
                "endpoint": dict(_STR, description="Filtrar por endpoint (opcional)."),
                "method": dict(_STR, description="Filtrar por método (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_api_contract": _meta(
        "get_api_contract",
        "api_contract:read",
        "api_contract",
        "backend",
        "Retorna um contrato de API por endpoint+method.",
        _schema(
            {
                "endpoint": dict(_STR, description="Path do endpoint."),
                "method": dict(_STR, description="Método HTTP."),
            },
            required=["endpoint", "method"],
        ),
    ),
    "delete_api_contract": _meta(
        "delete_api_contract",
        "api_contract:write",
        "api_contract",
        "backend",
        "Soft-delete de um contrato de API por endpoint+method.",
        _schema(
            {
                "endpoint": dict(_STR, description="Path do endpoint."),
                "method": dict(_STR, description="Método HTTP."),
            },
            required=["endpoint", "method"],
        ),
    ),
    # ── Database Schemas (histórico) ───────────────────────────────────────── #
    "save_database_schema": _meta(
        "save_database_schema",
        "database_schema:write",
        "database_schema",
        "backend",
        "Persiste um schema de banco fornecido pelo agente (atributos/relacionamentos/índices).",
        _schema(
            {
                "entity": dict(_STR, description="Entidade/tabela alvo."),
                "database_name": dict(_STR, description="Engine (postgres/mysql/...)."),
                "attributes": dict(_ARR, description="Atributos {name,type,...} (opcional)."),
                "relationships": dict(_ARR, description="Relacionamentos (opcional)."),
                "indexes": dict(_ARR, description="Índices (opcional)."),
                "constraints": dict(_ARR, description="Constraints (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["entity", "database_name"],
        ),
    ),
    "list_database_schemas": _meta(
        "list_database_schemas",
        "database_schema:read",
        "database_schema",
        "backend",
        "Lista schemas de banco persistidos, com filtros opcionais.",
        _schema(
            {
                "entity": dict(_STR, description="Filtrar por entidade (opcional)."),
                "database_name": dict(_STR, description="Filtrar por engine (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_database_schema": _meta(
        "get_database_schema",
        "database_schema:read",
        "database_schema",
        "backend",
        "Retorna um schema de banco persistido (atributos/relacionamentos/índices) por id.",
        _schema({"id": dict(_INT, description="Id do schema.")}, required=["id"]),
    ),
    "update_database_schema": _meta(
        "update_database_schema",
        "database_schema:write",
        "database_schema",
        "backend",
        "Atualiza campos mutáveis de um schema de banco.",
        _schema(
            {
                "id": dict(_INT, description="Id do schema."),
                "database_name": dict(_STR, description="Novo engine (opcional)."),
                "attributes": dict(_ARR, description="Novos atributos (opcional)."),
                "relationships": dict(_ARR, description="Novos relacionamentos (opcional)."),
                "indexes": dict(_ARR, description="Novos índices (opcional)."),
                "constraints": dict(_ARR, description="Novas constraints (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_database_schema": _meta(
        "delete_database_schema",
        "database_schema:write",
        "database_schema",
        "backend",
        "Soft-delete de um schema de banco por id.",
        _schema({"id": dict(_INT, description="Id do schema.")}, required=["id"]),
    ),
    # ── Auth Policies (upsert por resource) ────────────────────────────────── #
    "save_auth_policy": _meta(
        "save_auth_policy",
        "auth_policy:write",
        "auth_policy",
        "security",
        "Persiste (upsert) a política de auth de um recurso com os campos fornecidos.",
        _schema(
            {
                "resource": dict(_STR, description="Recurso protegido (chave natural única)."),
                "auth_type": dict(_STR, description="Tipo de auth (jwt/oauth/...)."),
                "roles": dict(_STR_ARR, description="Papéis autorizados (opcional)."),
                "data_sensitivity": dict(_STR, description="Sensibilidade do dado (opcional)."),
                "rules": dict(_OBJ, description="Regras adicionais (opcional)."),
                "status": dict(_STR, description="Status da política (opcional)."),
            },
            required=["resource", "auth_type"],
        ),
    ),
    "list_auth_policies": _meta(
        "list_auth_policies",
        "auth_policy:read",
        "auth_policy",
        "security",
        "Lista políticas de auth persistidas, com filtros opcionais.",
        _schema(
            {
                "auth_type": dict(_STR, description="Filtrar por tipo de auth (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_auth_policy": _meta(
        "get_auth_policy",
        "auth_policy:read",
        "auth_policy",
        "security",
        "Retorna a política de auth de um recurso.",
        _schema({"resource": dict(_STR, description="Recurso alvo.")}, required=["resource"]),
    ),
    "delete_auth_policy": _meta(
        "delete_auth_policy",
        "auth_policy:write",
        "auth_policy",
        "security",
        "Soft-delete da política de auth de um recurso.",
        _schema({"resource": dict(_STR, description="Recurso alvo.")}, required=["resource"]),
    ),
    # ── Backend Artifacts (histórico append-only) ──────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "backend",
        "Persiste um artefato de código backend (router/migration/service/...) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: router|migration|service_layer|repository|openapi_spec|"
                        "nestjs_controller|integration."
                    ),
                ),
                "target": dict(_STR, description="Alvo (nome/módulo/serviço)."),
                "content": dict(_STR, description="Código gerado pelo agente."),
                "language": dict(_STR, description="Linguagem (python/typescript/...; opcional)."),
                "framework": dict(_STR, description="Framework (fastapi/nestjs/...; opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "backend",
        "Lista artefatos de código persistidos, com filtros opcionais.",
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
        "backend",
        "Retorna um artefato de código backend persistido (router/migration/service/...) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "backend",
        "Soft-delete de um artefato de código por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Code Reviews (histórico append-only) ───────────────────────────────── #
    "save_code_review": _meta(
        "save_code_review",
        "code_review:write",
        "code_review",
        "backend",
        "Persiste uma revisão de código backend (achados/scores) fornecida pelo agente.",
        _schema(
            {
                "target": dict(_STR, description="Arquivo/módulo/serviço revisado."),
                "language": dict(_STR, description="Linguagem (python/typescript/...)."),
                "focus": dict(_STR_ARR, description="Focos da revisão (opcional)."),
                "findings": dict(_ARR, description="Achados da revisão (opcional)."),
                "security_score": dict(_NUM, description="Score de segurança (opcional)."),
                "performance_score": dict(_NUM, description="Score de performance (opcional)."),
                "summary": dict(_STR, description="Resumo da revisão (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["target", "language"],
        ),
    ),
    "list_code_reviews": _meta(
        "list_code_reviews",
        "code_review:read",
        "code_review",
        "backend",
        "Lista revisões de código persistidas, com filtros opcionais.",
        _schema(
            {
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "language": dict(_STR, description="Filtrar por linguagem (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_code_review": _meta(
        "get_code_review",
        "code_review:read",
        "code_review",
        "backend",
        "Retorna uma revisão de código backend persistida (achados/scores) por id.",
        _schema({"id": dict(_INT, description="Id da revisão.")}, required=["id"]),
    ),
    "delete_code_review": _meta(
        "delete_code_review",
        "code_review:write",
        "code_review",
        "backend",
        "Soft-delete de uma revisão de código por id.",
        _schema({"id": dict(_INT, description="Id da revisão.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes stateful seguem `<resource_type>:<acao>` com :read
    # p/ consultas e :write p/ mutações do estado do tenant. Geradores não LEEM nem
    # GRAVAM estado — só computam scaffold de backend — então nenhum dos dois cabe.
    # Escolha: nova ação `:generate` sobre o resource_type coerente com o artefato
    # que cada gerador produz (o mesmo domínio da sua contraparte persistida):
    # least-privilege real (um token só de geração não abre leitura/escrita do
    # estado). data_domain acompanha a contraparte (backend / security).
    "generate_fastapi_router": _meta(
        "generate_fastapi_router",
        "artifact:generate",
        "artifact",
        "backend",
        "Gera o scaffold de um APIRouter FastAPI determinístico a partir de resource+routes.",
        _schema(
            {
                "resource": dict(_STR, description="Recurso/entidade do router (usado no prefix/tag)."),
                "routes": dict(
                    _ARR,
                    description="Rotas [{method,path,handler}]; path params viram args do handler.",
                ),
                "prefix": dict(_STR, description="Prefixo do router (default '/<resource>')."),
            },
            required=["resource", "routes"],
        ),
    ),
    "generate_service_layer": _meta(
        "generate_service_layer",
        "artifact:generate",
        "artifact",
        "backend",
        "Gera o scaffold de uma classe de service determinística a partir de entity+methods.",
        _schema(
            {
                "entity": dict(_STR, description="Entidade alvo (nome da classe de service)."),
                "methods": dict(
                    _ARR,
                    description="Métodos (str ou {name}); default CRUD (create/get/list/update/delete).",
                ),
            },
            required=["entity"],
        ),
    ),
    "generate_repository_layer": _meta(
        "generate_repository_layer",
        "artifact:generate",
        "artifact",
        "backend",
        "Gera o scaffold de um repositório ORM async determinístico a partir de entity+fields.",
        _schema(
            {
                "entity": dict(_STR, description="Entidade alvo (nome da classe/tabela)."),
                "fields": dict(_ARR, description="Campos [{name,type}] (documentados nas colunas)."),
            },
            required=["entity"],
        ),
    ),
    "generate_database_schema": _meta(
        "generate_database_schema",
        "database_schema:generate",
        "database_schema",
        "backend",
        "Gera DDL SQL (CREATE TABLE) determinístico a partir de tables[{name,columns[{name,type,pk,fk}]}].",
        _schema(
            {
                "tables": dict(
                    _ARR,
                    description="Tabelas [{name, columns:[{name,type,pk?,fk?}]}].",
                ),
            },
            required=["tables"],
        ),
    ),
    "generate_migration": _meta(
        "generate_migration",
        "database_schema:generate",
        "database_schema",
        "backend",
        "Gera um esqueleto de migration alembic (upgrade/downgrade) determinístico a partir de revision+ops.",
        _schema(
            {
                "revision": dict(_STR, description="Id da revisão."),
                "ops": dict(
                    _ARR,
                    description="Operações (str SQL ou {op,table,column?,type?}); downgrade é o inverso.",
                ),
                "down_revision": dict(_STR, description="Revisão anterior (opcional)."),
                "message": dict(_STR, description="Mensagem/descrição da migration (opcional)."),
            },
            required=["revision", "ops"],
        ),
    ),
    "generate_api_contract": _meta(
        "generate_api_contract",
        "api_contract:generate",
        "api_contract",
        "backend",
        "Gera um fragmento OpenAPI 3.1 (YAML) determinístico a partir de title+paths.",
        _schema(
            {
                "title": dict(_STR, description="Título da API."),
                "paths": dict(
                    _ARR,
                    description="Paths [{path,method,summary?,operationId?,status?}].",
                ),
                "version": dict(_STR, description="Versão da API (default '1.0.0')."),
            },
            required=["title", "paths"],
        ),
    ),
    "generate_auth_policy": _meta(
        "generate_auth_policy",
        "auth_policy:generate",
        "auth_policy",
        "security",
        "Gera um documento de política RBAC (Markdown) determinístico a partir de roles/resources/rules.",
        _schema(
            {
                "roles": dict(_STR_ARR, description="Papéis do RBAC."),
                "resources": dict(_STR_ARR, description="Recursos protegidos."),
                "rules": dict(
                    _ARR,
                    description="Regras [{role,resource,actions,effect}] (opcional).",
                ),
                "title": dict(_STR, description="Título do doc (default 'RBAC Policy')."),
            },
            required=["roles", "resources"],
        ),
    ),
    "generate_event_contracts": _meta(
        "generate_event_contracts",
        "artifact:generate",
        "artifact",
        "backend",
        "Gera um schema de eventos (YAML, JSON-Schema-like) determinístico a partir de events[{name,fields}]",
        _schema(
            {
                "events": dict(
                    _ARR,
                    description="Eventos [{name, fields}] (fields: dict {name:type} ou lista).",
                ),
                "version": dict(_STR, description="Versão do contrato (default '1.0')."),
            },
            required=["events"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: BackendStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). ``name`` é o nome de op SEM prefixo de
    domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_fastapi_router":
        return generate_fastapi_router(args)
    if name == "generate_service_layer":
        return generate_service_layer(args)
    if name == "generate_repository_layer":
        return generate_repository_layer(args)
    if name == "generate_database_schema":
        return generate_database_schema(args)
    if name == "generate_migration":
        return generate_migration(args)
    if name == "generate_api_contract":
        return generate_api_contract(args)
    if name == "generate_auth_policy":
        return generate_auth_policy(args)
    if name == "generate_event_contracts":
        return generate_event_contracts(args)
    # ── API Contracts ──────────────────────────────────────────────────────── #
    if name == "save_api_contract":
        return await save_api_contract(
            store,
            endpoint=args["endpoint"],
            method=args["method"],
            description=args.get("description"),
            request_schema=args.get("request_schema"),
            response_schema=args.get("response_schema"),
            status_codes=args.get("status_codes"),
            status=args.get("status"),
        )
    if name == "list_api_contracts":
        return await list_api_contracts(
            store,
            endpoint=args.get("endpoint"),
            method=args.get("method"),
            status=args.get("status"),
        )
    if name == "get_api_contract":
        return await get_api_contract(store, endpoint=args["endpoint"], method=args["method"])
    if name == "delete_api_contract":
        return await delete_api_contract(store, endpoint=args["endpoint"], method=args["method"])
    # ── Database Schemas ───────────────────────────────────────────────────── #
    if name == "save_database_schema":
        return await save_database_schema(
            store,
            entity=args["entity"],
            database_name=args["database_name"],
            attributes=args.get("attributes"),
            relationships=args.get("relationships"),
            indexes=args.get("indexes"),
            constraints=args.get("constraints"),
            status=args.get("status"),
        )
    if name == "list_database_schemas":
        return await list_database_schemas(
            store,
            entity=args.get("entity"),
            database_name=args.get("database_name"),
            status=args.get("status"),
        )
    if name == "get_database_schema":
        return await get_database_schema(store, schema_id=args["id"])
    if name == "update_database_schema":
        return await update_database_schema(
            store,
            schema_id=args["id"],
            database_name=args.get("database_name"),
            attributes=args.get("attributes"),
            relationships=args.get("relationships"),
            indexes=args.get("indexes"),
            constraints=args.get("constraints"),
            status=args.get("status"),
        )
    if name == "delete_database_schema":
        return await delete_database_schema(store, schema_id=args["id"])
    # ── Auth Policies ──────────────────────────────────────────────────────── #
    if name == "save_auth_policy":
        return await save_auth_policy(
            store,
            resource=args["resource"],
            auth_type=args["auth_type"],
            roles=args.get("roles"),
            data_sensitivity=args.get("data_sensitivity"),
            rules=args.get("rules"),
            status=args.get("status"),
        )
    if name == "list_auth_policies":
        return await list_auth_policies(store, auth_type=args.get("auth_type"), status=args.get("status"))
    if name == "get_auth_policy":
        return await get_auth_policy(store, resource=args["resource"])
    if name == "delete_auth_policy":
        return await delete_auth_policy(store, resource=args["resource"])
    # ── Backend Artifacts ──────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            language=args.get("language"),
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
    # ── Code Reviews ───────────────────────────────────────────────────────── #
    if name == "save_code_review":
        return await save_code_review(
            store,
            target=args["target"],
            language=args["language"],
            focus=args.get("focus"),
            findings=args.get("findings"),
            security_score=args.get("security_score"),
            performance_score=args.get("performance_score"),
            summary=args.get("summary"),
            status=args.get("status"),
        )
    if name == "list_code_reviews":
        return await list_code_reviews(
            store, target=args.get("target"), language=args.get("language"), status=args.get("status")
        )
    if name == "get_code_review":
        return await get_code_review(store, review_id=args["id"])
    if name == "delete_code_review":
        return await delete_code_review(store, review_id=args["id"])
    raise KeyError(name)
