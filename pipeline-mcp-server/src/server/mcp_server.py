"""Servidor MCP pipeline — 14 tools para gerenciamento de pipeline DEV→HML→PROD.

Regras de aprovação:
  DEV  (PRs → develop):     pipeline-mcp auto-aprova e mergia autonomamente
  HML  (develop → homol):   pipeline-mcp cria PR, aguarda aprovação humana
  PROD (homol → main):      pipeline-mcp cria PR, aguarda aprovação humana

Tools:
  Pipeline (8):  register_pipeline, get_pipeline, list_pipeline,
                 promote_service, approve_promotion, watch_prs,
                 block_service, rollback
  Gates (3):     add_gate_result, get_gate_status, clear_gates
  History (3):   get_promotion_history, get_pipeline_overview, set_pipeline_config
"""

from __future__ import annotations

import os

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi import FastAPI
from mcp.types import TextContent, Tool

from ..config.settings import PipelineSettings, get_settings
from ..db.store import PipelineStore
from ..tools import (
    add_gate_result,
    approve_promotion,
    block_service,
    clear_gates,
    get_gate_status,
    get_pipeline,
    get_pipeline_overview,
    get_promotion_history,
    list_pipeline,
    promote_service,
    register_pipeline,
    rollback,
    set_pipeline_config,
    watch_prs,
)

_log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────── #
# Schemas                                                                      #
# ─────────────────────────────────────────────────────────────────────────── #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Pipeline ──────────────────────────────────────────────────────────── #
    "register_pipeline": {
        "description": (
            "Registra um serviço no pipeline. "
            "Se o serviço já existir, atualiza repo e base_branch. "
            "Retorna action=created ou action=updated."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome único do serviço."},
                "repo": {
                    "type": "string",
                    "description": "Nome do repositório (ex: org/repo-name).",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Branch base de desenvolvimento. Default: develop.",
                    "default": "develop",
                },
            },
            "required": ["service", "repo"],
            "additionalProperties": False,
        },
    },
    "get_pipeline": {
        "description": (
            "Retorna o status atual do pipeline de um serviço, "
            "incluindo ambiente atual, status de bloqueio e últimas 10 promoções."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
            },
            "required": ["service"],
            "additionalProperties": False,
        },
    },
    "list_pipeline": {
        "description": (
            "Lista serviços registrados no pipeline. "
            "Suporta filtros por env (dev/homol/prod/blocked/rollback) e status (active/blocked)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod", "blocked", "rollback"],
                    "description": "Filtrar por ambiente atual do serviço.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "blocked"],
                    "description": "Filtrar por status de bloqueio.",
                },
            },
            "additionalProperties": False,
        },
    },
    "promote_service": {
        "description": (
            "Promove um serviço entre ambientes (dev→homol ou homol→prod). "
            "Verifica todos os gates obrigatórios antes de promover. "
            "DEV→HML e HML→PROD: cria PR via GitHub e aguarda aprovação humana (status=waiting_approval). "
            "Após aprovação humana, chame approve_promotion(promotion_id). "
            "Retorna can_promote=false com lista de gates pendentes se houver falhas."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "from_env": {
                    "type": "string",
                    "enum": ["dev", "homol"],
                    "description": "Ambiente de origem.",
                },
                "to_env": {
                    "type": "string",
                    "enum": ["homol", "prod"],
                    "description": "Ambiente de destino.",
                },
                "promoted_by": {
                    "type": "string",
                    "description": "Identificador de quem solicitou a promoção (usuário ou agente).",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo da promoção (opcional).",
                },
            },
            "required": ["service", "from_env", "to_env", "promoted_by"],
            "additionalProperties": False,
        },
    },
    "approve_promotion": {
        "description": (
            "Registra aprovação humana de uma promoção HML ou PROD e executa o merge da PR. "
            "Deve ser chamado após o humano aprovar a PR no GitHub. "
            "Atualiza o ambiente do serviço para to_env após merge bem-sucedido."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "promotion_id": {
                    "type": "integer",
                    "description": "ID da promoção retornado por promote_service.",
                },
                "approved_by": {
                    "type": "string",
                    "description": "Identificador de quem aprovou (usuário GitHub ou nome).",
                },
            },
            "required": ["promotion_id", "approved_by"],
            "additionalProperties": False,
        },
    },
    "watch_prs": {
        "description": (
            "Escaneia PRs abertas nos repos registrados no pipeline. "
            "PRs targeting 'develop': auto-aprova e mergia se gates passam (DEV — autonomia total). "
            "PRs targeting 'homol' ou 'main': lista para aprovação humana sem tocar. "
            "Configure PIPELINE_GITHUB_TOKEN e PIPELINE_GITHUB_ORG para usar."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repos específicos a verificar. Default: todos os registrados no pipeline.",
                },
            },
            "additionalProperties": False,
        },
    },
    "block_service": {
        "description": (
            "Bloqueia a promoção de um serviço no pipeline. "
            "Um serviço bloqueado não pode ser promovido até ser desbloqueado manualmente."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "reason": {"type": "string", "description": "Motivo do bloqueio."},
                "blocked_by": {
                    "type": "string",
                    "description": "Identificador de quem bloqueou.",
                },
            },
            "required": ["service", "reason", "blocked_by"],
            "additionalProperties": False,
        },
    },
    "rollback": {
        "description": (
            "Registra um rollback de versão para um serviço em um ambiente. "
            "Atualiza o status do serviço para 'rollback' e registra no histórico."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente onde o rollback será realizado.",
                },
                "to_version": {
                    "type": "string",
                    "description": "Versão/SHA/tag para onde reverter.",
                },
                "rolled_back_by": {
                    "type": "string",
                    "description": "Identificador de quem executou o rollback.",
                },
                "reason": {
                    "type": "string",
                    "description": "Motivo do rollback (opcional).",
                },
            },
            "required": ["service", "env", "to_version", "rolled_back_by"],
            "additionalProperties": False,
        },
    },
    # ── Gates ─────────────────────────────────────────────────────────────── #
    "add_gate_result": {
        "description": (
            "Registra o resultado de um gate de qualidade para um serviço/ambiente. "
            "Types válidos: qa_tests, security_scan, pr_approved, health_check, manual_approval. "
            "Se o gate já existir, atualiza o resultado."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente ao qual o gate se refere.",
                },
                "gate_type": {
                    "type": "string",
                    "enum": [
                        "qa_tests",
                        "security_scan",
                        "pr_approved",
                        "health_check",
                        "manual_approval",
                    ],
                    "description": "Tipo do gate.",
                },
                "passed": {
                    "type": "boolean",
                    "description": "True se o gate passou, False se falhou.",
                },
                "details": {
                    "type": "string",
                    "description": "Detalhes adicionais (URL do relatório, mensagem de erro, etc.).",
                },
                "evaluated_by": {
                    "type": "string",
                    "description": "Identificador de quem/o que avaliou o gate.",
                },
            },
            "required": ["service", "env", "gate_type", "passed"],
            "additionalProperties": False,
        },
    },
    "get_gate_status": {
        "description": (
            "Retorna o status de todos os gates para um serviço/ambiente. "
            "Indica quais gates são obrigatórios, quais passaram, falharam ou estão ausentes. "
            "Inclui campo can_promote: true/false."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente a consultar.",
                },
            },
            "required": ["service", "env"],
            "additionalProperties": False,
        },
    },
    "clear_gates": {
        "description": (
            "Limpa todos os resultados de gates de um serviço/ambiente. "
            "Útil para forçar re-avaliação completa antes de uma nova promoção."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "env": {
                    "type": "string",
                    "enum": ["dev", "homol", "prod"],
                    "description": "Ambiente cujos gates serão limpos.",
                },
            },
            "required": ["service", "env"],
            "additionalProperties": False,
        },
    },
    # ── History ───────────────────────────────────────────────────────────── #
    "get_promotion_history": {
        "description": (
            "Retorna o histórico de promoções. "
            "Se service for fornecido, filtra pelo serviço. "
            "Retorna até limit registros ordenados por data decrescente."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Nome do serviço (opcional, para filtrar).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                    "description": "Número máximo de registros. Default: 20.",
                },
            },
            "additionalProperties": False,
        },
    },
    "get_pipeline_overview": {
        "description": (
            "Retorna visão geral do pipeline: total de serviços por ambiente, "
            "contagem de bloqueados/ativos, e serviços com gates com falha."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "set_pipeline_config": {
        "description": (
            "Configura quais gates são obrigatórios por ambiente para um serviço. "
            "Substitui a configuração padrão (homol: [qa_tests, pr_approved]; "
            "prod: [qa_tests, security_scan, pr_approved, health_check])."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço."},
                "gates_required": {
                    "type": "object",
                    "description": (
                        "Mapa de ambiente → lista de gates obrigatórios. "
                        'Ex: {"homol": ["qa_tests"], "prod": ["qa_tests", "pr_approved"]}'
                    ),
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "required": ["service", "gates_required"],
            "additionalProperties": False,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────── #
# HTTP API sidecar                                                              #
# ─────────────────────────────────────────────────────────────────────────── #
def _start_http_api(store: PipelineStore, settings: PipelineSettings) -> None:
    """Inicia HTTP API mínima em thread daemon para consulta por outros MCPs."""
    app = FastAPI(title="pipeline-mcp API", version="0.1.0", docs_url="/docs")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            pipelines = store.list_pipelines()
            count = len(pipelines)
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "error": str(exc)}
        return {
            "status": "ok",
            "service": "pipeline-mcp",
            "registered_pipelines": count,
        }

    @app.get("/v1/pipeline/{service}")
    def get_service_pipeline(service: str) -> dict[str, Any]:
        pipeline = store.get_pipeline(service)
        if pipeline is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Service '{service}' not found")
        return pipeline

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "pipeline-mcp", "docs": "/docs", "health": "/api/health"}

    cfg = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=settings.api_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True, name="pipeline-mcp-http")
    thread.start()
    _log.info("pipeline_mcp_http_started port=%d", settings.api_port)


# ─────────────────────────────────────────────────────────────────────────── #
# Server                                                                       #
# ─────────────────────────────────────────────────────────────────────────── #
def build_server(settings: PipelineSettings, store: PipelineStore) -> Server:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if settings.api_enabled:
        _start_http_api(store, settings)
    server: Server = Server("pipeline-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        args = arguments or {}
        _log.info("tool_called: %s keys=%s", name, sorted(args.keys()))
        try:
            payload = _dispatch(name, args, settings, store)
        except KeyError:
            payload = {"error": "UnknownTool", "tool": name}
            _log.error("unknown_tool: %s", name)
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: PipelineSettings,
    store: PipelineStore,
) -> dict:
    # ── Pipeline ──────────────────────────────────────────────────────────── #
    if name == "register_pipeline":
        return register_pipeline(
            store,
            service=args["service"],
            repo=args["repo"],
            base_branch=args.get("base_branch", "develop"),
        )
    if name == "get_pipeline":
        return get_pipeline(store, service=args["service"])
    if name == "list_pipeline":
        return list_pipeline(
            store,
            env=args.get("env"),
            status=args.get("status"),
        )
    if name == "promote_service":
        return promote_service(
            store,
            service=args["service"],
            from_env=args["from_env"],
            to_env=args["to_env"],
            promoted_by=args["promoted_by"],
            reason=args.get("reason"),
            github_token=settings.github_token,
            github_org=settings.github_org,
        )
    if name == "approve_promotion":
        return approve_promotion(
            store,
            promotion_id=args["promotion_id"],
            approved_by=args["approved_by"],
            github_token=settings.github_token,
            github_org=settings.github_org,
        )
    if name == "watch_prs":
        return watch_prs(
            store,
            github_token=settings.github_token,
            github_org=settings.github_org,
            repos=args.get("repos"),
        )
    if name == "block_service":
        return block_service(
            store,
            service=args["service"],
            reason=args["reason"],
            blocked_by=args["blocked_by"],
        )
    if name == "rollback":
        return rollback(
            store,
            service=args["service"],
            env=args["env"],
            to_version=args["to_version"],
            rolled_back_by=args["rolled_back_by"],
            reason=args.get("reason"),
        )
    # ── Gates ─────────────────────────────────────────────────────────────── #
    if name == "add_gate_result":
        return add_gate_result(
            store,
            service=args["service"],
            env=args["env"],
            gate_type=args["gate_type"],
            passed=args["passed"],
            details=args.get("details"),
            evaluated_by=args.get("evaluated_by"),
        )
    if name == "get_gate_status":
        return get_gate_status(store, service=args["service"], env=args["env"])
    if name == "clear_gates":
        return clear_gates(store, service=args["service"], env=args["env"])
    # ── History ───────────────────────────────────────────────────────────── #
    if name == "get_promotion_history":
        return get_promotion_history(
            store,
            service=args.get("service"),
            limit=args.get("limit", 20),
        )
    if name == "get_pipeline_overview":
        return get_pipeline_overview(store)
    if name == "set_pipeline_config":
        return set_pipeline_config(
            store,
            service=args["service"],
            gates_required=args["gates_required"],
        )

    raise KeyError(name)


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, *rest = build_server()
    http_app = rest[-1]

    cfg = uvicorn.Config(
        http_app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7100")),
        log_level="warning", access_log=False,
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
    asyncio.run(_run())


if __name__ == "__main__":
    main()
