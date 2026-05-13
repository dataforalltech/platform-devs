"""Servidor MCP services — 14 tools para registro e monitoramento de serviços.

Tools:
  Registry (5):   register_service, get_service, list_services, update_service, unregister_service
  PortMap (2):    get_port_map, find_by_port
  Discovery (4):  scan_docker, scan_processes, check_health, check_all_health
  Composite (3):  service_status, list_environments, reload_service
"""

from __future__ import annotations


import os

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import ServicesSettings, get_settings
from ..db.store import ServiceStore
from ..tools import (
    check_all_health,
    check_health,
    find_by_port,
    get_port_map,
    get_service,
    list_environments,
    list_services,
    register_service,
    reload_service,
    scan_docker,
    scan_processes,
    service_status,
    unregister_service,
    update_service,
)

_log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────── #
# Schemas                                                                      #
# ─────────────────────────────────────────────────────────────────────────── #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Registry ──────────────────────────────────────────────────────────── #
    "register_service": {
        "description": (
            "Registra ou atualiza um serviço no registry local. "
            "Se o serviço já existir, atualiza os campos fornecidos. "
            "Retorna action=created ou action=updated."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome único do serviço."},
                "host": {
                    "type": "string",
                    "description": "Host onde o serviço roda. Default: localhost.",
                    "default": "localhost",
                },
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "Porta TCP do serviço.",
                },
                "url": {
                    "type": "string",
                    "description": "URL base do serviço (ex: http://localhost:8080).",
                },
                "type": {
                    "type": "string",
                    "enum": ["docker", "process", "remote", "unknown"],
                    "description": "Tipo do serviço. Default: unknown.",
                    "default": "unknown",
                },
                "environment": {
                    "type": "string",
                    "enum": ["local", "dev", "hml", "prod"],
                    "description": "Ambiente do serviço. Default: local.",
                    "default": "local",
                },
                "health_path": {
                    "type": "string",
                    "description": "Path do health check. Default: /health.",
                    "default": "/health",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags para classificação.",
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Metadados extras (chave-valor livre).",
                },
            },
            "required": ["name", "port"],
            "additionalProperties": False,
        },
    },
    "get_service": {
        "description": "Retorna os dados de um serviço pelo nome.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do serviço."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "list_services": {
        "description": (
            "Lista serviços registrados. "
            "Suporta filtros por environment, type, status e tag."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "enum": ["local", "dev", "hml", "prod"],
                    "description": "Filtrar por ambiente.",
                },
                "type": {
                    "type": "string",
                    "enum": ["docker", "process", "remote", "unknown"],
                    "description": "Filtrar por tipo.",
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "stopped", "unknown"],
                    "description": "Filtrar por status.",
                },
                "tag": {
                    "type": "string",
                    "description": "Filtrar por tag.",
                },
            },
            "additionalProperties": False,
        },
    },
    "update_service": {
        "description": (
            "Atualiza campos de um serviço existente. "
            "Pelo menos um campo deve ser informado além do name."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do serviço a atualizar."},
                "host": {"type": "string"},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "url": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["docker", "process", "remote", "unknown"],
                },
                "environment": {
                    "type": "string",
                    "enum": ["local", "dev", "hml", "prod"],
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "stopped", "unknown"],
                },
                "health_path": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "unregister_service": {
        "description": "Remove um serviço do registry.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do serviço a remover."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    # ── PortMap ───────────────────────────────────────────────────────────── #
    "get_port_map": {
        "description": (
            "Retorna mapa de porta → serviço para todos os serviços registrados com porta. "
            "Útil para detectar conflitos de porta."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "find_by_port": {
        "description": "Encontra o serviço registrado em uma porta específica.",
        "schema": {
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "Porta TCP a consultar.",
                },
            },
            "required": ["port"],
            "additionalProperties": False,
        },
    },
    # ── Discovery ─────────────────────────────────────────────────────────── #
    "scan_docker": {
        "description": (
            "Executa `docker ps` e sincroniza containers em execução no registry. "
            "Requer Docker instalado e acessível no PATH."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 60,
                    "description": "Timeout em segundos para o comando docker. Default: 10.",
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
    },
    "scan_processes": {
        "description": (
            "Usa psutil para listar processos em LISTEN. "
            "Retorna lista de processos com pid, nome e porta."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "min_port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "Porta mínima a incluir. Default: 1024.",
                    "default": 1024,
                },
            },
            "additionalProperties": False,
        },
    },
    "check_health": {
        "description": (
            "Realiza HTTP GET no health endpoint de um serviço registrado. "
            "Atualiza last_check_at e last_check_ok no registry."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do serviço."},
                "timeout": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 30.0,
                    "description": "Timeout HTTP em segundos. Default: 3.0.",
                    "default": 3.0,
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "check_all_health": {
        "description": (
            "Verifica saúde de todos os serviços com health_path definido. "
            "Atualiza status automaticamente: healthy→running, unhealthy→stopped."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 30.0,
                    "description": "Timeout HTTP em segundos. Default: 3.0.",
                    "default": 3.0,
                },
            },
            "additionalProperties": False,
        },
    },
    # ── Composite ─────────────────────────────────────────────────────────── #
    "service_status": {
        "description": (
            "Retorna dados do serviço + health check em uma única chamada. "
            "overall_status: healthy | unhealthy | unknown."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do serviço."},
                "timeout": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 30.0,
                    "description": "Timeout HTTP em segundos. Default: 3.0.",
                    "default": 3.0,
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "list_environments": {
        "description": (
            "Agrupa serviços por environment e retorna contagens. "
            "Mostra total/running/stopped/unknown por ambiente."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "reload_service": {
        "description": (
            "Recarrega/reinicia um serviço registrado. "
            "Estratégia automática por tipo: "
            "docker → `docker restart <name>` | "
            "process → mata processo na porta (espera reinício pelo process manager) | "
            "remote → POST em /reload ou /actuator/restart | "
            "unknown → re-verifica health. "
            "Aguarda wait_seconds e faz health check automático após o reload."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do serviço a recarregar."},
                "wait_seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 60,
                    "default": 3.0,
                    "description": "Segundos para aguardar antes de verificar health. Default: 3.",
                },
                "health_timeout": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 30,
                    "default": 5.0,
                    "description": "Timeout do health check pós-reload em segundos. Default: 5.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────── #
# HTTP API (sidecar para discovery por outros MCPs, ex: agent-twin)            #
# ─────────────────────────────────────────────────────────────────────────── #
def _build_http_app(store: ServiceStore) -> FastAPI:
    app = FastAPI(title="services-mcp API", version="0.1.0", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        try:
            count = len(store.list_all())
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "error": str(exc)}
        return {"status": "ok", "service": "services-mcp", "registered_services": count}

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "services-mcp", "docs": "/docs", "health": "/v1/health"}

    return app


# ─────────────────────────────────────────────────────────────────────────── #
# Server                                                                       #
# ─────────────────────────────────────────────────────────────────────────── #
def build_server() -> tuple[Any, ServiceStore, ServicesSettings, FastAPI]:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    store = ServiceStore(settings)
    http_app = _build_http_app(store)

    _log.info("services_mcp_ready")

    server: Server = Server("services-mcp-server")

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

    @http_app.get("/mcp/tools/list")
    async def http_list_tools() -> dict:
        tools = await list_tools()
        return {"result": {"tools": [t.model_dump(exclude_none=True) for t in tools]}}

    @http_app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> dict:
        params = body.get("params", body)
        result = await call_tool(params.get("name", ""), params.get("arguments", {}))
        return {"result": {"content": [r.model_dump(exclude_none=True) for r in result]}}

    return server, store, settings, http_app


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: ServicesSettings,
    store: ServiceStore,
) -> dict:
    # ── Registry ──────────────────────────────────────────────────────────── #
    if name == "register_service":
        return register_service(
            store,
            name=args["name"],
            port=args["port"],
            host=args.get("host", "localhost"),
            url=args.get("url"),
            health_path=args.get("health_path", "/health"),
            tags=args.get("tags"),
            metadata=args.get("metadata"),
            type=args.get("type", "unknown"),
            environment=args.get("environment", "local"),
        )
    if name == "get_service":
        return get_service(store, name=args["name"])
    if name == "list_services":
        return list_services(
            store,
            environment=args.get("environment"),
            tag=args.get("tag"),
            type=args.get("type"),
            status=args.get("status"),
        )
    if name == "update_service":
        update_args = {k: v for k, v in args.items() if k != "name"}
        return update_service(store, name=args["name"], **update_args)
    if name == "unregister_service":
        return unregister_service(store, name=args["name"])
    # ── PortMap ───────────────────────────────────────────────────────────── #
    if name == "get_port_map":
        return get_port_map(store)
    if name == "find_by_port":
        return find_by_port(store, port=args["port"])
    # ── Discovery ─────────────────────────────────────────────────────────── #
    if name == "scan_docker":
        return scan_docker(store, timeout=args.get("timeout", settings.docker_timeout))
    if name == "scan_processes":
        return scan_processes(store, min_port=args.get("min_port", 1024))
    if name == "check_health":
        return check_health(
            store, name=args["name"], timeout=args.get("timeout", settings.health_timeout)
        )
    if name == "check_all_health":
        return check_all_health(store, timeout=args.get("timeout", settings.health_timeout))
    # ── Composite ─────────────────────────────────────────────────────────── #
    if name == "service_status":
        return service_status(
            store, name=args["name"], timeout=args.get("timeout", settings.health_timeout)
        )
    if name == "list_environments":
        return list_environments(store)
    if name == "reload_service":
        return reload_service(
            store,
            name=args["name"],
            wait_seconds=args.get("wait_seconds", 3.0),
            health_timeout=args.get("health_timeout", settings.health_timeout),
        )

    raise KeyError(name)


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, _store, _settings, http_app = build_server()

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
