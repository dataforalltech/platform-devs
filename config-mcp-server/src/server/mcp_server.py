"""Servidor MCP config — 14 tools para credenciais, ambientes, tenants e hardware.

Tools:
  Credentials (5): get_credential, set_credential, set_credential_secure,
                   list_credentials, delete_credential
  Env (4):         get_env_config, set_env_var, list_environments, sync_env_file
  Sysinfo (1):     get_physical_info
  Tenants (4):     get_tenant_config, set_tenant_config, list_tenants,
                   get_session_tenant_config

HTTP API na porta 7100:
  Consumida por outros MCP servers (deploy-mcp, qa-mcp, etc.) via ConfigClient.
  Ver shared/config_client.py para o cliente.
Modo híbrido: stdio (para Claude/registry) + HTTP (para gateway e cross-MCP).
"""
from __future__ import annotations

import os

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI
from mcp.types import TextContent, Tool

from ..api.router import make_router
from ..config.settings import ConfigMcpSettings, get_settings
from ..knowledge.encryptor import Encryptor
from ..knowledge.store import ConfigStore
from ..tools import (
    delete_credential,
    get_credential,
    get_env_config,
    get_physical_info,
    get_session_tenant_config,
    get_tenant_config,
    list_credentials,
    list_environments,
    list_tenants,
    set_credential,
    set_credential_secure,
    set_env_var,
    set_tenant_config,
    sync_env_file,
)

_log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────── #
# Schemas                                                                      #
# ─────────────────────────────────────────────────────────────────────────── #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Credentials ───────────────────────────────────────────────────────── #
    "get_credential": {
        "description": (
            "Recupera um valor de credencial do store central. "
            "Namespaces convencionais: credentials.acr, credentials.github, "
            "credentials.portainer, credentials.internal.\n\n"
            "Use list_credentials para ver quais chaves estão disponíveis."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace da credencial. Ex: 'credentials.acr', 'credentials.github'.",
                },
                "key": {
                    "type": "string",
                    "description": "Nome da variável. Ex: 'ACR_USERNAME', 'GITHUB_TOKEN'.",
                },
            },
            "required": ["namespace", "key"],
            "additionalProperties": False,
        },
    },
    "set_credential": {
        "description": (
            "Define (cria ou atualiza) uma credencial no store central. "
            "O valor é armazenado encriptado com Fernet. "
            "Credenciais armazenadas aqui podem ser consultadas por qualquer MCP "
            "via HTTP API interna (config-mcp:7099)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Ex: 'credentials.acr', 'credentials.github', 'credentials.portainer'.",
                },
                "key": {"type": "string", "description": "Nome da variável."},
                "value": {"type": "string", "description": "Valor da credencial (será encriptado)."},
                "description": {
                    "type": "string",
                    "description": "Descrição opcional para documentação.",
                },
            },
            "required": ["namespace", "key", "value"],
            "additionalProperties": False,
        },
    },
    "set_credential_secure": {
        "description": (
            "Define uma credencial via input seguro no terminal (getpass). "
            "O valor nunca trafega pelo canal MCP — digitado diretamente no TTY do config-mcp. "
            "Use para senhas e tokens altamente sensíveis."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Ex: 'credentials.e2e', 'credentials.acr', 'credentials.github'.",
                },
                "key": {
                    "type": "string",
                    "description": "Nome da variável sensível. Ex: 'E2E_USER_PASSWORD', 'ACR_PASSWORD'.",
                },
            },
            "required": ["namespace", "key"],
            "additionalProperties": False,
        },
    },
    "list_credentials": {
        "description": (
            "Lista namespaces e chaves disponíveis no store. "
            "Nunca exibe valores — apenas as chaves. "
            "Use get_credential para recuperar um valor específico."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Filtrar por namespace. Default: todos.",
                },
            },
            "additionalProperties": False,
        },
    },
    "delete_credential": {
        "description": "Remove uma credencial do store central.",
        "schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "key": {"type": "string"},
            },
            "required": ["namespace", "key"],
            "additionalProperties": False,
        },
    },
    # ── Env ───────────────────────────────────────────────────────────────── #
    "get_env_config": {
        "description": "Retorna variáveis de um perfil de ambiente (dev/staging/production).",
        "schema": {
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "description": "Perfil. Ex: 'dev', 'staging', 'production'.",
                },
                "key_pattern": {
                    "type": "string",
                    "description": "Filtrar variáveis por nome (substring). Ex: 'DATABASE'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de variáveis retornadas. Padrão: 50.",
                    "default": 50,
                },
            },
            "required": ["environment"],
            "additionalProperties": False,
        },
    },
    "set_env_var": {
        "description": "Define uma variável de ambiente para um perfil específico.",
        "schema": {
            "type": "object",
            "properties": {
                "environment": {"type": "string", "description": "Ex: 'dev', 'staging', 'production'."},
                "key": {"type": "string", "description": "Nome da variável. Ex: 'DATABASE_URL'."},
                "value": {"type": "string", "description": "Valor da variável."},
            },
            "required": ["environment", "key", "value"],
            "additionalProperties": False,
        },
    },
    "list_environments": {
        "description": "Lista os ambientes configurados e a quantidade de variáveis em cada um.",
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "sync_env_file": {
        "description": (
            "Gera ou atualiza um arquivo .env com as variáveis do store para um ambiente. "
            "Com merge=true (padrão), mantém variáveis locais que não estão no store. "
            "Com merge=false, sobrescreve completamente o arquivo."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "target_path": {
                    "type": "string",
                    "description": "Caminho do arquivo .env. Ex: '/path/to/repo/.env.dev'.",
                },
                "environment": {
                    "type": "string",
                    "description": "Perfil cujas variáveis serão escritas. Ex: 'dev'.",
                },
                "merge": {
                    "type": "boolean",
                    "description": "Manter variáveis locais não presentes no store. Default: true.",
                    "default": True,
                },
            },
            "required": ["target_path", "environment"],
            "additionalProperties": False,
        },
    },
    # ── Sysinfo ───────────────────────────────────────────────────────────── #
    "get_physical_info": {
        "description": (
            "Coleta informações do ambiente físico atual: "
            "sistema operacional (OS, release, hostname), "
            "CPU (cores físicos/lógicos, frequência, uso%), "
            "RAM (total, disponível, uso%), "
            "discos (device, mountpoint, fstype, total/usado/livre GB), "
            "rede (interface → IP)."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    # ── Tenants ───────────────────────────────────────────────────────────── #
    "get_tenant_config": {
        "description": "Retorna variáveis de configuração de um tenant.",
        "schema": {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "Identificador do tenant. Ex: 'tenant_abc123'.",
                },
                "key_pattern": {
                    "type": "string",
                    "description": "Filtrar variáveis por nome (substring). Ex: 'DATABASE'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de variáveis retornadas. Padrão: 50.",
                    "default": 50,
                },
            },
            "required": ["tenant_id"],
            "additionalProperties": False,
        },
    },
    "set_tenant_config": {
        "description": "Define uma variável de configuração para um tenant.",
        "schema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "key": {"type": "string", "description": "Ex: 'DATABASE_URL'."},
                "value": {"type": "string"},
            },
            "required": ["tenant_id", "key", "value"],
            "additionalProperties": False,
        },
    },
    "list_tenants": {
        "description": "Lista todos os tenants configurados e a quantidade de variáveis de cada um.",
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "get_session_tenant_config": {
        "description": (
            "Retorna config do tenant da sessão autenticada atual. "
            "Resolve tenant_id automaticamente via agent-twin-mcp (:7098) — "
            "o agente não precisa conhecer o tenant_id."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────── #
# HTTP API (sidecar para outros MCPs)                                          #
# ─────────────────────────────────────────────────────────────────────────── #
def _build_http_app(store: ConfigStore, settings: ConfigMcpSettings) -> FastAPI:
    """Constrói a FastAPI app para config-mcp HTTP na porta 7100."""
    app = FastAPI(title="config-mcp API", version="0.1.0", docs_url="/docs")
    router = make_router(store, settings.api_token)
    app.include_router(router)
    return app


# ─────────────────────────────────────────────────────────────────────────── #
# MCP Server                                                                   #
# ─────────────────────────────────────────────────────────────────────────── #
def build_server() -> tuple[Any, ConfigStore, ConfigMcpSettings, FastAPI]:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    encryptor = Encryptor(settings.master_key)
    # Valida Fernet key imediatamente — falha rápida no startup
    try:
        encryptor.decrypt(encryptor.encrypt("_health_check_"))
    except Exception:
        _log.critical("invalid_or_missing_master_key — abortando.")
        raise SystemExit(1)
    store = ConfigStore(settings.store_path, encryptor)

    http_app = _build_http_app(store, settings)

    _log.info(
        "config_mcp_ready store=%s",
        settings.store_path,
    )

    server: Server = Server("config-mcp-server")

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
            payload = _dispatch(name, args, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
            _log.error("unknown_tool: %s", name)
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, store, settings, http_app


def _dispatch(name: str, args: dict[str, Any], store: ConfigStore) -> dict:
    # ── Credentials ───────────────────────────────────────────────────────── #
    if name == "get_credential":
        return get_credential(store, namespace=args["namespace"], key=args["key"])
    if name == "set_credential":
        return set_credential(
            store,
            namespace=args["namespace"],
            key=args["key"],
            value=args["value"],
            description=args.get("description"),
        )
    if name == "set_credential_secure":
        return set_credential_secure(store, namespace=args["namespace"], key=args["key"])
    if name == "list_credentials":
        return list_credentials(store, namespace=args.get("namespace"))
    if name == "delete_credential":
        return delete_credential(store, namespace=args["namespace"], key=args["key"])
    # ── Env ───────────────────────────────────────────────────────────────── #
    if name == "get_env_config":
        return get_env_config(
            store,
            environment=args["environment"],
            key_pattern=args.get("key_pattern"),
            limit=args.get("limit", 50),
        )
    if name == "set_env_var":
        return set_env_var(store, environment=args["environment"], key=args["key"], value=args["value"])
    if name == "list_environments":
        return list_environments(store)
    if name == "sync_env_file":
        return sync_env_file(
            store,
            target_path=args["target_path"],
            environment=args["environment"],
            merge=args.get("merge", True),
        )
    # ── Sysinfo ───────────────────────────────────────────────────────────── #
    if name == "get_physical_info":
        return get_physical_info()
    # ── Tenants ───────────────────────────────────────────────────────────── #
    if name == "get_tenant_config":
        return get_tenant_config(
            store,
            tenant_id=args["tenant_id"],
            key_pattern=args.get("key_pattern"),
            limit=args.get("limit", 50),
        )
    if name == "set_tenant_config":
        return set_tenant_config(
            store, tenant_id=args["tenant_id"], key=args["key"], value=args["value"]
        )
    if name == "list_tenants":
        return list_tenants(store)
    if name == "get_session_tenant_config":
        return get_session_tenant_config(store)

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
