"""Servidor MCP do docs — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:docs-mcp) via JWKS
     do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O inner
     token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (health/status, sem token) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: docs-mcp indexa/audita documentação e persiste histórico num store
PostgreSQL próprio (src/db/store.py). Não há backend REST — o `_dispatch` recebe
`store`/`settings` e chama as tools diretamente.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings, get_settings
from ..db.store import DocsStore
from ..tools.audit_tool import (
    audit_repo,
    find_stale_docs,
    generate_doc_report,
    get_audit_history,
)
from ..tools.scan_tool import get_doc_tree, scan_docs, search_docs
from ..tools.standards_tool import check_doc_standards
from ..tools.template_tool import generate_doc, list_templates
from ..tools.validation_tool import (
    check_links,
    check_required_docs,
    lint_markdown,
    validate_doc,
)

_log = logging.getLogger(__name__)

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Análise/scan/validação → verbo :read; geração de artefato → :write.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "scan_docs": {
        "description": (
            "Encontra todos os arquivos de documentação em repo_path. "
            "Detecta tipo (readme, changelog, adr, etc.) e indexa no store."
        ),
        "capability": "docs-mcp.scan_docs",
        "required_scope": "docs-mcp:index:read",
        "resource_type": "doc_index",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Padrões glob (default: ['**/*.md', '**/*.rst', '**/*.txt'])",
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Incluir arquivos/diretórios ocultos",
                    "default": False,
                },
            },
            "required": ["repo_path"],
        },
    },
    "search_docs": {
        "description": (
            "Busca full-text em todos os docs do repo_path. "
            "Retorna trechos (snippets) ao redor de cada match."
        ),
        "capability": "docs-mcp.search_docs",
        "required_scope": "docs-mcp:index:read",
        "resource_type": "doc_index",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "query": {
                    "type": "string",
                    "description": "Texto a buscar nos documentos",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Busca case-sensitive",
                    "default": False,
                },
                "file_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extensões a buscar (ex: ['md', 'rst'])",
                },
            },
            "required": ["repo_path", "query"],
        },
    },
    "get_doc_tree": {
        "description": (
            "Retorna estrutura hierárquica de todos os arquivos de documentação. "
            "Agrupa por diretório com resumo de tipos e contagem de palavras."
        ),
        "capability": "docs-mcp.get_doc_tree",
        "required_scope": "docs-mcp:index:read",
        "resource_type": "doc_index",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
            },
            "required": ["repo_path"],
        },
    },
    "validate_doc": {
        "description": (
            "Valida documento contra regras do tipo (seções, mínimo de palavras, status ADR). "
            "Auto-detecta tipo pelo nome."
        ),
        "capability": "docs-mcp.validate_doc",
        "required_scope": "docs-mcp:validation:read",
        "resource_type": "validation",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo markdown",
                },
                "doc_type": {
                    "type": "string",
                    "enum": ["auto", "readme", "changelog", "adr", "agents", "runbook", "api"],
                    "description": "Tipo do documento (auto = detecta pelo nome)",
                    "default": "auto",
                },
            },
            "required": ["file_path"],
        },
    },
    "check_links": {
        "description": (
            "Detecta links quebrados em markdown. "
            "Verifica links internos (existência de arquivo), âncoras (#heading) "
            "e opcionalmente links externos via HTTP."
        ),
        "capability": "docs-mcp.check_links",
        "required_scope": "docs-mcp:validation:read",
        "resource_type": "validation",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo markdown",
                },
                "check_external": {
                    "type": "boolean",
                    "description": "Verificar links externos via HTTP (lento)",
                },
            },
            "required": ["file_path"],
        },
    },
    "check_required_docs": {
        "description": (
            "Verifica se o repositório tem os arquivos obrigatórios "
            "para o nível de standard: minimal, standard, full ou service."
        ),
        "capability": "docs-mcp.check_required_docs",
        "required_scope": "docs-mcp:validation:read",
        "resource_type": "validation",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "standard": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full", "service"],
                    "description": "Nível de exigência documental",
                    "default": "standard",
                },
            },
            "required": ["repo_path"],
        },
    },
    "lint_markdown": {
        "description": (
            "Linting de markdown: headings, blocos de código, links vazios, "
            "headings duplicados, linhas longas e h1 ausente."
        ),
        "capability": "docs-mcp.lint_markdown",
        "required_scope": "docs-mcp:validation:read",
        "resource_type": "validation",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo markdown",
                },
            },
            "required": ["file_path"],
        },
    },
    "list_templates": {
        "description": (
            "Retorna catálogo de templates disponíveis: README, CHANGELOG, ADR, "
            "AGENTS, RUNBOOK e API. Inclui variáveis e caso de uso de cada template."
        ),
        "capability": "docs-mcp.list_templates",
        "required_scope": "docs-mcp:template:read",
        "resource_type": "template",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "generate_doc": {
        "description": (
            "Gera documento a partir de template com substituição {{var}}. "
            "Salva no disco se output_path fornecido."
        ),
        "capability": "docs-mcp.generate_doc",
        "required_scope": "docs-mcp:template:write",
        "resource_type": "template",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "template_name": {
                    "type": "string",
                    "enum": ["README", "CHANGELOG", "ADR", "AGENTS", "RUNBOOK", "API"],
                    "description": "Nome do template a usar",
                },
                "variables": {
                    "type": "object",
                    "description": "Mapa de variáveis para substituição (ex: {service_name: 'meu-serviço'})",
                    "additionalProperties": {"type": "string"},
                },
                "output_path": {
                    "type": "string",
                    "description": "Caminho absoluto para salvar o arquivo gerado (opcional)",
                },
            },
            "required": ["template_name", "variables"],
        },
    },
    "check_doc_standards": {
        "description": (
            "Verifica padrões documentais (completeness, validity, quality). "
            "Retorna score 0-100 e grade A-F."
        ),
        "capability": "docs-mcp.check_doc_standards",
        "required_scope": "docs-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "standard": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full", "service"],
                    "description": "Nível de exigência documental",
                    "default": "standard",
                },
            },
            "required": ["repo_path"],
        },
    },
    "audit_repo": {
        "description": (
            "Auditoria completa: required docs, padrões e docs desatualizados. "
            "Score ponderado; salva no histórico do store."
        ),
        "capability": "docs-mcp.audit_repo",
        "required_scope": "docs-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "standard": {
                    "type": "string",
                    "enum": ["minimal", "standard", "full", "service"],
                    "description": "Nível de exigência documental",
                    "default": "standard",
                },
            },
            "required": ["repo_path"],
        },
    },
    "find_stale_docs": {
        "description": (
            "Detecta documentos não atualizados há mais de X dias. "
            "Usa `git log` para obter data do último commit; fallback para mtime."
        ),
        "capability": "docs-mcp.find_stale_docs",
        "required_scope": "docs-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "days_threshold": {
                    "type": "integer",
                    "description": "Dias sem atualização para considerar stale (default: settings.stale_days_threshold)",
                },
            },
            "required": ["repo_path"],
        },
    },
    "get_audit_history": {
        "description": (
            "Retorna histórico de auditorias salvas no store, "
            "ordenadas pela mais recente. Filtra por repo_path opcionalmente."
        ),
        "capability": "docs-mcp.get_audit_history",
        "required_scope": "docs-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Filtrar por repositório (opcional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de auditorias a retornar",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
    "generate_doc_report": {
        "description": (
            "Relatório de qualidade documental com score, grade, trend e action items. "
            "Executa audit_repo se não houver histórico."
        ),
        "capability": "docs-mcp.generate_doc_report",
        "required_scope": "docs-mcp:audit:read",
        "resource_type": "audit",
        "data_domain": "documentation",
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
            },
            "required": ["repo_path"],
        },
    },
}

_EXPECTED = {
    "scan_docs",
    "search_docs",
    "get_doc_tree",
    "validate_doc",
    "check_links",
    "check_required_docs",
    "lint_markdown",
    "list_templates",
    "generate_doc",
    "check_doc_standards",
    "audit_repo",
    "find_stale_docs",
    "get_audit_history",
    "generate_doc_report",
}

if set(_TOOL_SCHEMAS.keys()) != _EXPECTED:  # integridade do catálogo (falha no import)
    raise RuntimeError(f"Tool mismatch: {set(_TOOL_SCHEMAS.keys()) ^ _EXPECTED}")

# Health/status são encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless).
# docs-mcp não expõe tool de status; a liveness é o próprio /v1/health.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:docs-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:docs-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (recebe store/settings; tenant_id só para governança) ──────────


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: Settings,
    store: DocsStore,
) -> dict[str, Any]:
    """Despacha a chamada para a função de tool. tenant_id é injetado pelo PEP nos
    args (INV-3); as tools extraem apenas seus parâmetros nomeados, ignorando-o."""
    # ---- scan_tool ----
    if name == "scan_docs":
        return scan_docs(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            patterns=args.get("patterns"),
            include_hidden=args.get("include_hidden", False),
        )
    if name == "search_docs":
        return search_docs(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            query=args.get("query", ""),
            case_sensitive=args.get("case_sensitive", False),
            file_types=args.get("file_types"),
        )
    if name == "get_doc_tree":
        return get_doc_tree(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
        )
    # ---- validation_tool ----
    if name == "validate_doc":
        return validate_doc(
            store,
            settings,
            file_path=args.get("file_path", ""),
            doc_type=args.get("doc_type", "auto"),
        )
    if name == "check_links":
        return check_links(
            store,
            settings,
            file_path=args.get("file_path", ""),
            check_external=args.get("check_external"),
        )
    if name == "check_required_docs":
        return check_required_docs(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            standard=args.get("standard", "standard"),
        )
    if name == "lint_markdown":
        return lint_markdown(
            store,
            settings,
            file_path=args.get("file_path", ""),
        )
    # ---- template_tool ----
    if name == "list_templates":
        return list_templates()
    if name == "generate_doc":
        return generate_doc(
            store,
            settings,
            template_name=args.get("template_name", ""),
            variables=args.get("variables") or {},
            output_path=args.get("output_path"),
        )
    # ---- standards_tool ----
    if name == "check_doc_standards":
        return check_doc_standards(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            standard=args.get("standard", "standard"),
        )
    # ---- audit_tool ----
    if name == "audit_repo":
        return audit_repo(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            standard=args.get("standard", "standard"),
        )
    if name == "find_stale_docs":
        return find_stale_docs(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            days_threshold=args.get("days_threshold"),
        )
    if name == "get_audit_history":
        return get_audit_history(
            store,
            settings,
            repo_path=args.get("repo_path"),
            limit=args.get("limit", 10),
        )
    if name == "generate_doc_report":
        return generate_doc_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
        )
    raise KeyError(name)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: Settings, store: DocsStore) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="docs-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "docs-mcp", "tools": len(_TOOL_SCHEMAS)}

    @app.get("/mcp/tools/list")
    def http_list_tools() -> dict:
        tools = []
        for name, meta in _TOOL_SCHEMAS.items():
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            }
            entry.update({f: meta[f] for f in _POLICY_FIELDS})
            tools.append(entry)
        return {"result": {"tools": tools}}

    @app.post("/mcp/tools/call")
    def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Execução (não-exempt) exige inner token válido; tenant vem dos claims.
        if name not in _EXEMPT_TOOLS:
            twin_token = (params.get("_meta") or {}).get("twin_token")
            if not twin_token:
                return JSONResponse(status_code=401, content={"error": "missing_twin_token"})
            try:
                claims = _verify_inner_token(twin_token, settings)
            except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha de verificação
                _log.warning("inner_token_rejected tool=%s detail=%s", name, exc)
                return JSONResponse(status_code=401, content={"error": "invalid_twin_token"})
            tenant_id = claims.get("tenant_id")
            if not tenant_id:
                return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})
            # SEC-035 / INV-3: tenant SEMPRE dos claims, nunca de argumento do cliente.
            arguments["tenant_id"] = tenant_id

        try:
            payload = _dispatch(name, arguments, settings, store)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, Settings, DocsStore, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o store e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    store = DocsStore(settings=settings)
    http_app = _build_http_app(settings, store)
    _log.info("docs_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    server: Server = Server("docs-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, settings, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, store, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, _store, http_app = build_server()
    cfg = uvicorn.Config(
        http_app,
        host="0.0.0.0",  # noqa: S104 — bind interno do container; ingress só via gateway (INV-1)
        port=settings.mcp_port,
        log_level="warning",
        access_log=False,
    )
    server_http = uvicorn.Server(cfg)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await asyncio.gather(
                server.run(read_stream, write_stream, server.create_initialization_options()),
                server_http.serve(),
            )
    except (EOFError, BrokenPipeError):
        pass


def main() -> None:
    # MCP_HTTP_ONLY=1 → só o sidecar HTTP (uso típico atrás do gateway, sem stdio).
    if os.getenv("MCP_HTTP_ONLY", "0") == "1":
        import uvicorn

        _server, settings, _store, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
