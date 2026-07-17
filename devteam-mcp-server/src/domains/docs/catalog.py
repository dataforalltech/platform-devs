"""Catálogo de tools + dispatcher do domínio *docs* (consolidado no devteam-mcp).

Fatia "de negócio" do antigo `docs-mcp-server/src/server/mcp_server.py`: mantém intactos
o ``_TOOL_SCHEMAS`` (schemas + metadados de policy por tool), a guarda de integridade
``_EXPECTED`` e o roteamento (``_dispatch`` op → handler). O que ficou de FORA é o
boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) — responsabilidade
do AGREGADOR (`src/server/mcp_server.py`), compartilhada por todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.docs_<op>`` (namespace do server consolidado +
    nome de tool já prefixado pelo domínio — o gateway não deriva por nome).
  * ``required_scope`` passa a ``docs:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool (data_domain=documentation), só troca o antigo prefixo de namespace
    ``docs-mcp`` pelo domínio canônico ``docs``.
  * As CHAVES de ``_TOOL_SCHEMAS`` continuam os nomes de op SEM prefixo (``scan_docs``); o
    ``plugin.register()`` prefixa (``docs_scan_docs``) e o ``plugin.dispatch`` retira o
    prefixo antes de chamar ``dispatch`` daqui — a lógica de roteamento fica byte-a-byte.
  * O ``_run_tool``/``_ensure_tenant_schema`` do fonte somem: o agregador já garante o
    schema e abre a sessão tenant-scoped; a ``dispatch`` daqui recebe a ``DocsStore`` da
    sessão. O ``settings`` (thresholds/flags do domínio) é uma dep de RUNTIME construída
    aqui (``get_settings()``) — as 10 tools compute-only o consultam, as 4 de persistência
    usam o store.
"""

from __future__ import annotations

from typing import Any

from .config.settings import Settings, get_settings
from .db.store import DocsStore
from .tools.audit_tool import (
    audit_repo,
    find_stale_docs,
    generate_doc_report,
    get_audit_history,
)
from .tools.scan_tool import get_doc_tree, scan_docs, search_docs
from .tools.standards_tool import check_doc_standards
from .tools.template_tool import generate_doc, list_templates
from .tools.validation_tool import (
    check_links,
    check_required_docs,
    lint_markdown,
    validate_doc,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "docs"

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
        "capability": "devteam-mcp.docs_scan_docs",
        "required_scope": "docs:index:read",
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
        "capability": "devteam-mcp.docs_search_docs",
        "required_scope": "docs:index:read",
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
        "capability": "devteam-mcp.docs_get_doc_tree",
        "required_scope": "docs:index:read",
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
        "capability": "devteam-mcp.docs_validate_doc",
        "required_scope": "docs:validation:read",
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
        "capability": "devteam-mcp.docs_check_links",
        "required_scope": "docs:validation:read",
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
        "capability": "devteam-mcp.docs_check_required_docs",
        "required_scope": "docs:validation:read",
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
        "capability": "devteam-mcp.docs_lint_markdown",
        "required_scope": "docs:validation:read",
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
        "capability": "devteam-mcp.docs_list_templates",
        "required_scope": "docs:template:read",
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
        "capability": "devteam-mcp.docs_generate_doc",
        "required_scope": "docs:template:write",
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
            "Verifica padrões documentais (completeness, validity, quality). Retorna score 0-100 e grade A-F."
        ),
        "capability": "devteam-mcp.docs_check_doc_standards",
        "required_scope": "docs:audit:read",
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
        "capability": "devteam-mcp.docs_audit_repo",
        "required_scope": "docs:audit:read",
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
        "capability": "devteam-mcp.docs_find_stale_docs",
        "required_scope": "docs:audit:read",
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
        "capability": "devteam-mcp.docs_get_audit_history",
        "required_scope": "docs:audit:read",
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
        "capability": "devteam-mcp.docs_generate_doc_report",
        "required_scope": "docs:audit:read",
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


# ── Dispatcher (recebe store; settings é dep de RUNTIME; tenant só p/ governança) ──


async def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: Settings,
    store: DocsStore,
) -> dict[str, Any]:
    """Despacha a chamada para a função de tool (async). O tenant NÃO viaja nos args
    (INV-3): o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner
    token). As 10 tools compute-only recebem o store mas ignoram o DB; as 4 tools de
    persistência (scan_docs/audit_repo/get_audit_history/generate_doc_report) são async."""
    # ---- scan_tool ----
    if name == "scan_docs":
        return await scan_docs(
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
        return await audit_repo(
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
        return await get_audit_history(
            store,
            settings,
            repo_path=args.get("repo_path"),
            limit=args.get("limit", 10),
        )
    if name == "generate_doc_report":
        return await generate_doc_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
        )
    raise KeyError(name)


async def dispatch(name: str, args: dict[str, Any], store: DocsStore) -> dict[str, Any]:
    """Ponto de entrada do domínio (chamado pelo ``plugin.dispatch``). ``name`` é o nome de
    op SEM prefixo de domínio (o ``plugin.dispatch`` já o retirou) e o ``store`` já está
    ligado ao pool do tenant. Constrói o ``settings`` (dep de RUNTIME: thresholds/flags do
    domínio — ``get_settings()``) e delega ao ``_dispatch`` copiado byte-a-byte do fonte."""
    settings = get_settings()
    return await _dispatch(name, args, settings, store)
