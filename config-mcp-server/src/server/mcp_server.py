"""Servidor MCP config — 21 tools para credenciais, ambientes, tenants, hardware e workspace.

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
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..api.router import make_router
from ..config.settings import ConfigMcpSettings, get_settings
from ..knowledge.encryptor import Encryptor
from ..knowledge.store import ConfigStore
from ..tools import (
    audit_env_files,
    delete_credential,
    get_credential,
    get_env_config,
    get_physical_info,
    get_session_tenant_config,
    get_tenant_config,
    get_workspace_config,
    list_credentials,
    list_environments,
    list_tenants,
    list_workspace_config,
    push_env_to_store,
    read_env_file,
    redact_env_secrets,
    set_credential,
    set_credential_secure,
    set_env_var,
    set_tenant_config,
    set_workspace_config,
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
    # ── Env (file-based) ─────────────────────────────────────────────────────── #
    "read_env_file": {
        "description": (
            "Le um arquivo .env do disco e retorna as variaveis como dict. "
            "Complemento ao get_env_config que le do store encriptado."
        ),
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Caminho absoluto do arquivo .env."},
                "key_filter": {"type": "string", "description": "Filtro substring nas chaves (case-insensitive). Ex: 'URL'."},
            },
        },
    },
    "audit_env_files": {
        "description": (
            "Escaneia todos os arquivos .env.* de um diretorio e reporta problemas. "
            "Detecta secrets hardcoded (JWT_SECRET_KEY, DB_PASSWORD, TOKEN...), "
            "arquivos fora do padrao canonico, e verifica cobertura no ConfigStore."
        ),
        "schema": {
            "type": "object",
            "required": ["directory"],
            "additionalProperties": False,
            "properties": {
                "directory": {"type": "string", "description": "Caminho do diretorio a escanear (ex: /path/to/platform-auth)."},
                "include_pattern": {"type": "string", "default": ".env*", "description": "Glob para os arquivos. Default: .env*."},
                "check_store": {"type": "boolean", "default": True, "description": "Verificar se os secrets ja estao no ConfigStore. Default: true."},
            },
        },
    },
    "redact_env_secrets": {
        "description": (
            "Substitui valores hardcoded de secrets por ${VAR_NAME} em arquivos .env. "
            "Ex: JWT_SECRET_KEY=XrDsC... vira JWT_SECRET_KEY=${JWT_SECRET_KEY}. "
            "Use dry_run=true para simular antes de aplicar."
        ),
        "schema": {
            "type": "object",
            "required": ["paths"],
            "additionalProperties": False,
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Lista de caminhos dos arquivos .env."},
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Chaves explicitas a redact. Se omitido, usa auto_detect."},
                "auto_detect": {"type": "boolean", "default": True, "description": "Detectar automaticamente via padrao de nomes. Default: true."},
                "dry_run": {"type": "boolean", "default": False, "description": "Simular sem alterar arquivos. Default: false."},
            },
        },
    },
    "push_env_to_store": {
        "description": (
            "Le um arquivo .env do disco e importa as variaveis para o ConfigStore encriptado "
            "no namespace env.<environment>. Ideal para inicializar o store a partir de um arquivo existente. "
            "Apos o push, use sync_env_file para gerar arquivos .env a partir do store."
        ),
        "schema": {
            "type": "object",
            "required": ["path", "environment"],
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo .env a importar."},
                "environment": {"type": "string", "description": "Perfil de ambiente destino (ex: 'dev', 'local')."},
                "overwrite": {"type": "boolean", "default": False, "description": "Sobrescrever vars ja existentes no store. Default: false."},
                "secrets_only": {"type": "boolean", "default": False, "description": "Importar apenas vars identificadas como secrets. Default: false."},
            },
        },
    },
    # ── Workspace ─────────────────────────────────────────────────────────── #
    "get_workspace_config": {
        "description": (
            "Le configuracao do workspace do namespace 'workspace' no ConfigStore. "
            "Chaves canonicas: REPOS_ROOT (pasta dos repos), PYTHON_BIN, EDITOR, DEFAULT_ENV. "
            "Se key for passado, retorna apenas aquela chave com fallback para variaveis de ambiente."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Chave especifica a ler (ex: REPOS_ROOT). Se omitido, retorna todas.",
                },
            },
        },
    },
    "set_workspace_config": {
        "description": (
            "Define ou atualiza uma chave no namespace 'workspace' do ConfigStore. "
            "Para REPOS_ROOT: valida que o caminho existe (use create_dir=true para criar). "
            "Outras chaves sao armazenadas livremente. "
            "Exemplo: set_workspace_config(key='REPOS_ROOT', value='/home/user/repos')."
        ),
        "schema": {
            "type": "object",
            "required": ["key", "value"],
            "additionalProperties": False,
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Nome da chave (ex: REPOS_ROOT, PYTHON_BIN, EDITOR, DEFAULT_ENV).",
                },
                "value": {
                    "type": "string",
                    "description": "Valor a armazenar.",
                },
                "create_dir": {
                    "type": "boolean",
                    "default": False,
                    "description": "Para REPOS_ROOT: cria o diretorio se nao existir. Default: false.",
                },
            },
        },
    },
    "list_workspace_config": {
        "description": (
            "Lista todas as chaves do namespace 'workspace' com valores e descricoes. "
            "Mostra quais chaves canonicas estao ausentes para facilitar o setup inicial. "
            "Chaves canonicas: REPOS_ROOT, PYTHON_BIN, EDITOR, DEFAULT_ENV."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
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
    if name == "read_env_file":
        return read_env_file(store, path=args["path"], key_filter=args.get("key_filter"))
    if name == "audit_env_files":
        return audit_env_files(
            store,
            directory=args["directory"],
            include_pattern=args.get("include_pattern", ".env*"),
            check_store=args.get("check_store", True),
        )
    if name == "redact_env_secrets":
        return redact_env_secrets(
            store,
            paths=args["paths"],
            keys=args.get("keys"),
            auto_detect=args.get("auto_detect", True),
            dry_run=args.get("dry_run", False),
        )
    if name == "push_env_to_store":
        return push_env_to_store(
            store,
            path=args["path"],
            environment=args["environment"],
            overwrite=args.get("overwrite", False),
            secrets_only=args.get("secrets_only", False),
        )
    # ── Workspace ─────────────────────────────────────────────────────────── #
    if name == "get_workspace_config":
        return get_workspace_config(store, key=args.get("key"))
    if name == "set_workspace_config":
        return set_workspace_config(
            store,
            key=args["key"],
            value=args["value"],
            create_dir=args.get("create_dir", False),
        )
    if name == "list_workspace_config":
        return list_workspace_config(store)
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
