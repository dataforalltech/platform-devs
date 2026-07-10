"""Servidor MCP do config — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0), espelhando o
architecture-mcp-server. Implementa o contrato de integração com o MCP Gateway
central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:config-mcp) via JWKS
     do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O inner
     token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3). Isolamento por tenant nas tools tenants.*.
  4. _EXEMPT_TOOLS (status/health, sem token) e _EXCLUDE_TOOLS (denylist fail-safe:
     tools que devolvem SEGREDO em claro ou dependem de TTY nunca saem pelo gateway).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: config-mcp é uma persona **stateful** (serve credenciais/ambientes/tenants a
partir de um ConfigStore encriptado local). O store É o backend — não há REST a
chamar —, por isso não há ServiceApiClient; o dispatcher recebe o `store` diretamente.
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

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Leituras usam verbo :read; mutações :write.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Status (exempt/health) ────────────────────────────────────────────── #
    "status": {
        "description": "Retorna o status real do servidor (nome, versão, nº de tools).",
        "capability": "config-mcp.status",
        "required_scope": "config-mcp:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    # ── Credentials (data_domain=secrets) ─────────────────────────────────── #
    "get_credential": {
        "description": (
            "Recupera um valor de credencial do store central. "
            "Namespaces convencionais: credentials.acr, credentials.github, "
            "credentials.portainer, credentials.internal.\n\n"
            "Use list_credentials para ver quais chaves estão disponíveis."
        ),
        "capability": "config-mcp.get_credential",
        "required_scope": "config-mcp:credential:read",
        "resource_type": "credential",
        "data_domain": "secrets",
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
            "O valor é armazenado encriptado com Fernet."
        ),
        "capability": "config-mcp.set_credential",
        "required_scope": "config-mcp:credential:write",
        "resource_type": "credential",
        "data_domain": "secrets",
        "schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Ex: 'credentials.acr', 'credentials.github', 'credentials.portainer'.",
                },
                "key": {"type": "string", "description": "Nome da variável."},
                "value": {
                    "type": "string",
                    "description": "Valor da credencial (será encriptado).",
                },
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
        "capability": "config-mcp.set_credential_secure",
        "required_scope": "config-mcp:credential:write",
        "resource_type": "credential",
        "data_domain": "secrets",
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
            "Lista namespaces e chaves disponíveis no store. Nunca exibe valores — apenas as chaves."
        ),
        "capability": "config-mcp.list_credentials",
        "required_scope": "config-mcp:credential:read",
        "resource_type": "credential",
        "data_domain": "secrets",
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
        "capability": "config-mcp.delete_credential",
        "required_scope": "config-mcp:credential:write",
        "resource_type": "credential",
        "data_domain": "secrets",
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
    # ── Env (data_domain=configuration) ───────────────────────────────────── #
    "get_env_config": {
        "description": "Retorna variáveis de um perfil de ambiente (dev/staging/production).",
        "capability": "config-mcp.get_env_config",
        "required_scope": "config-mcp:env:read",
        "resource_type": "env_config",
        "data_domain": "configuration",
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
        "capability": "config-mcp.set_env_var",
        "required_scope": "config-mcp:env:write",
        "resource_type": "env_config",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "description": "Ex: 'dev', 'staging', 'production'.",
                },
                "key": {"type": "string", "description": "Nome da variável. Ex: 'DATABASE_URL'."},
                "value": {"type": "string", "description": "Valor da variável."},
            },
            "required": ["environment", "key", "value"],
            "additionalProperties": False,
        },
    },
    "list_environments": {
        "description": "Lista os ambientes configurados e a quantidade de variáveis em cada um.",
        "capability": "config-mcp.list_environments",
        "required_scope": "config-mcp:env:read",
        "resource_type": "env_config",
        "data_domain": "configuration",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "sync_env_file": {
        "description": (
            "Gera ou atualiza um arquivo .env com as variáveis do store para um ambiente. "
            "Com merge=true (padrão), mantém variáveis locais que não estão no store."
        ),
        "capability": "config-mcp.sync_env_file",
        "required_scope": "config-mcp:env:write",
        "resource_type": "env_file",
        "data_domain": "configuration",
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
    "read_env_file": {
        "description": (
            "Le um arquivo .env do disco e retorna as variaveis como dict. "
            "Complemento ao get_env_config que le do store encriptado."
        ),
        "capability": "config-mcp.read_env_file",
        "required_scope": "config-mcp:env:read",
        "resource_type": "env_file",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Caminho absoluto do arquivo .env."},
                "key_filter": {
                    "type": "string",
                    "description": "Filtro substring nas chaves (case-insensitive). Ex: 'URL'.",
                },
            },
        },
    },
    "audit_env_files": {
        "description": (
            "Escaneia todos os arquivos .env.* de um diretorio e reporta problemas. "
            "Detecta secrets hardcoded, arquivos fora do padrao canonico, e cobertura no ConfigStore."
        ),
        "capability": "config-mcp.audit_env_files",
        "required_scope": "config-mcp:env:read",
        "resource_type": "env_file",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "required": ["directory"],
            "additionalProperties": False,
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Caminho do diretorio a escanear (ex: /path/to/platform-auth).",
                },
                "include_pattern": {
                    "type": "string",
                    "default": ".env*",
                    "description": "Glob para os arquivos. Default: .env*.",
                },
                "check_store": {
                    "type": "boolean",
                    "default": True,
                    "description": "Verificar se os secrets ja estao no ConfigStore. Default: true.",
                },
            },
        },
    },
    "redact_env_secrets": {
        "description": (
            "Substitui valores hardcoded de secrets por ${VAR_NAME} em arquivos .env. "
            "Use dry_run=true para simular antes de aplicar."
        ),
        "capability": "config-mcp.redact_env_secrets",
        "required_scope": "config-mcp:env:write",
        "resource_type": "env_file",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "required": ["paths"],
            "additionalProperties": False,
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de caminhos dos arquivos .env.",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Chaves explicitas a redact. Se omitido, usa auto_detect.",
                },
                "auto_detect": {
                    "type": "boolean",
                    "default": True,
                    "description": "Detectar automaticamente via padrao de nomes. Default: true.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Simular sem alterar arquivos. Default: false.",
                },
            },
        },
    },
    "push_env_to_store": {
        "description": (
            "Le um arquivo .env do disco e importa as variaveis para o ConfigStore encriptado "
            "no namespace env.<environment>."
        ),
        "capability": "config-mcp.push_env_to_store",
        "required_scope": "config-mcp:env:write",
        "resource_type": "env_config",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "required": ["path", "environment"],
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo .env a importar."},
                "environment": {
                    "type": "string",
                    "description": "Perfil de ambiente destino (ex: 'dev', 'local').",
                },
                "overwrite": {
                    "type": "boolean",
                    "default": False,
                    "description": "Sobrescrever vars ja existentes no store. Default: false.",
                },
                "secrets_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "Importar apenas vars identificadas como secrets. Default: false.",
                },
            },
        },
    },
    # ── Workspace (data_domain=configuration) ─────────────────────────────── #
    "get_workspace_config": {
        "description": (
            "Le configuracao do workspace do namespace 'workspace' no ConfigStore. "
            "Chaves canonicas: REPOS_ROOT, PYTHON_BIN, EDITOR, DEFAULT_ENV."
        ),
        "capability": "config-mcp.get_workspace_config",
        "required_scope": "config-mcp:workspace:read",
        "resource_type": "workspace_config",
        "data_domain": "configuration",
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
            "Para REPOS_ROOT: valida que o caminho existe (use create_dir=true para criar)."
        ),
        "capability": "config-mcp.set_workspace_config",
        "required_scope": "config-mcp:workspace:write",
        "resource_type": "workspace_config",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "required": ["key", "value"],
            "additionalProperties": False,
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Nome da chave (ex: REPOS_ROOT, PYTHON_BIN, EDITOR, DEFAULT_ENV).",
                },
                "value": {"type": "string", "description": "Valor a armazenar."},
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
            "Chaves canonicas: REPOS_ROOT, PYTHON_BIN, EDITOR, DEFAULT_ENV."
        ),
        "capability": "config-mcp.list_workspace_config",
        "required_scope": "config-mcp:workspace:read",
        "resource_type": "workspace_config",
        "data_domain": "configuration",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    # ── Sysinfo (data_domain=operational) ─────────────────────────────────── #
    "get_physical_info": {
        "description": ("Coleta informações do ambiente físico atual: OS, CPU, RAM, discos e rede."),
        "capability": "config-mcp.get_physical_info",
        "required_scope": "config-mcp:sysinfo:read",
        "resource_type": "system_info",
        "data_domain": "operational",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    # ── Tenants (data_domain=configuration; tenant_id vem das claims — INV-3) ─ #
    "get_tenant_config": {
        "description": (
            "Retorna variáveis de configuração do tenant. O tenant_id é resolvido das "
            "claims do inner token (gateway); via stdio direto pode ser informado."
        ),
        "capability": "config-mcp.get_tenant_config",
        "required_scope": "config-mcp:tenant:read",
        "resource_type": "tenant_config",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "properties": {
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
            "additionalProperties": False,
        },
    },
    "set_tenant_config": {
        "description": (
            "Define uma variável de configuração para o tenant. O tenant_id é resolvido "
            "das claims do inner token (gateway) — nunca de argumento do cliente (INV-3)."
        ),
        "capability": "config-mcp.set_tenant_config",
        "required_scope": "config-mcp:tenant:write",
        "resource_type": "tenant_config",
        "data_domain": "configuration",
        "schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Ex: 'DATABASE_URL'."},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        },
    },
    "list_tenants": {
        "description": "Lista todos os tenants configurados e a quantidade de variáveis de cada um.",
        "capability": "config-mcp.list_tenants",
        "required_scope": "config-mcp:tenant:read",
        "resource_type": "tenant_config",
        "data_domain": "configuration",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "get_session_tenant_config": {
        "description": (
            "Retorna config do tenant da sessão autenticada atual. Resolve tenant_id "
            "automaticamente via dev-twin-mcp — o agente não precisa conhecer o tenant_id."
        ),
        "capability": "config-mcp.get_session_tenant_config",
        "required_scope": "config-mcp:tenant:read",
        "resource_type": "tenant_config",
        "data_domain": "configuration",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

# Health/status são encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless).
_EXEMPT_TOOLS: frozenset[str] = frozenset({"status"})
# Denylist fail-safe (CI-7): tools que NUNCA devem sair pelo gateway.
#   get_credential        — devolve o SEGREDO em claro (risco de exfiltração p/ o agente).
#   set_credential_secure — depende de getpass no TTY do processo; travaria o worker HTTP.
_EXCLUDE_TOOLS: frozenset[str] = frozenset({"get_credential", "set_credential_secure"})

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:config-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:config-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatcher (stateful: recebe o ConfigStore) ───────────────────────────────


def _dispatch(name: str, args: dict[str, Any], store: ConfigStore) -> dict[str, Any]:
    """Despacha a chamada para a função de tool. tenant_id é injetado pelo PEP nos
    args a partir das claims (INV-3) e consumido pelas tools tenants.*."""
    if name == "status":
        return {"status": "ok", "service": "config-mcp", "tools": len(_TOOL_SCHEMAS)}
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
    # ── Sysinfo ───────────────────────────────────────────────────────────── #
    if name == "get_physical_info":
        return get_physical_info()
    # ── Tenants (tenant_id das claims — INV-3) ─────────────────────────────── #
    if name == "get_tenant_config":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"error": "missing_tenant", "hint": "tenant_id resolvido das claims do token."}
        return get_tenant_config(
            store,
            tenant_id=tenant_id,
            key_pattern=args.get("key_pattern"),
            limit=args.get("limit", 50),
        )
    if name == "set_tenant_config":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"error": "missing_tenant", "hint": "tenant_id resolvido das claims do token."}
        return set_tenant_config(store, tenant_id=tenant_id, key=args["key"], value=args["value"])
    if name == "list_tenants":
        return list_tenants(store)
    if name == "get_session_tenant_config":
        return get_session_tenant_config(store)

    raise KeyError(name)


# ── ConfigStore bootstrap (valida a chave Fernet — fail-fast) ─────────────────


def _build_store(settings: Settings) -> ConfigStore:
    """Constrói o ConfigStore e valida a master key imediatamente (fail-fast)."""
    try:
        encryptor = Encryptor(settings.master_key)
        encryptor.decrypt(encryptor.encrypt("_health_check_"))
    except Exception as exc:  # noqa: BLE001 — chave ausente/inválida = boot inviável
        _log.critical("invalid_or_missing_master_key — abortando.")
        raise SystemExit(1) from exc
    return ConfigStore(settings.store_path, encryptor)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: Settings, store: ConfigStore) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*)."""
    app = FastAPI(
        title="config-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "config-mcp", "tools": len(_TOOL_SCHEMAS)}

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
            except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha
                _log.warning("inner_token_rejected tool=%s detail=%s", name, exc)
                return JSONResponse(status_code=401, content={"error": "invalid_twin_token"})
            tenant_id = claims.get("tenant_id")
            if not tenant_id:
                return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})
            # SEC-035 / INV-3: tenant SEMPRE dos claims, nunca de argumento do cliente.
            arguments["tenant_id"] = tenant_id

        try:
            payload = _dispatch(name, arguments, store)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, Settings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o ConfigStore e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    store = _build_store(settings)
    http_app = _build_http_app(settings, store)
    _log.info("config_mcp_ready tools=%d store=%s", len(_TOOL_SCHEMAS), settings.store_path)

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
        try:
            payload = _dispatch(name, args, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, http_app = build_server()
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

        _server, settings, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
