"""Servidor MCP de Documentação — 14 tools para scan, validação, templates e auditoria."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from ..config.settings import DocsSettings, get_settings
from ..db.store import DocsStore
from ..tools.audit_tool import audit_repo, find_stale_docs, generate_doc_report, get_audit_history
from ..tools.scan_tool import get_doc_tree, scan_docs, search_docs
from ..tools.standards_tool import check_doc_standards
from ..tools.template_tool import generate_doc, list_templates
from ..tools.validation_tool import (
    check_links,
    check_required_docs,
    lint_markdown,
    validate_doc,
)

# ---------------------------------------------------------------------- #
# Schemas                                                                 #
# ---------------------------------------------------------------------- #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "scan_docs": {
        "description": (
            "Encontra todos os arquivos de documentação em repo_path. "
            "Detecta tipo (readme, changelog, adr, etc.) e indexa no SQLite."
        ),
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
            "Score ponderado; salva no histórico SQLite."
        ),
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
            "Retorna histórico de auditorias salvas no SQLite, "
            "ordenadas pela mais recente. Filtra por repo_path opcionalmente."
        ),
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

assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED, (
    f"Tool mismatch: {set(_TOOL_SCHEMAS.keys()) ^ _EXPECTED}"
)


# ---------------------------------------------------------------------- #
# Server                                                                  #
# ---------------------------------------------------------------------- #
def build_server() -> tuple[Server, DocsSettings, DocsStore]:
    settings = get_settings()
    store = DocsStore(db_path=settings.db_path)
    server: Server = Server("docs-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=meta["description"],
                inputSchema=meta["schema"],
            )
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, settings, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(exc), "tool": name}

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, store


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: DocsSettings,
    store: DocsStore,
) -> dict:
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


async def _run() -> None:
    server, _settings, _store = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
