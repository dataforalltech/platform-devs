"""Catálogo de tools + dispatcher do domínio *config* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `config-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``dispatch`` (roteamento op → handler, byte-a-byte do ``_dispatch`` do fonte). O que
ficou de FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant
plumbing, encryptor bootstrap) — isso é responsabilidade do AGREGADOR
(`src/server/mcp_server.py`) e do ``plugin`` do domínio.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.config_<op>`` (namespace do server consolidado
    + nome de tool já prefixado pelo domínio — o gateway não deriva por nome).
  * ``required_scope`` passa a ``config:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool (data_domain intacto), só troca o antigo prefixo de namespace ``config-mcp``
    pelo domínio canônico ``config``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo (``status``);
    o ``plugin.register()`` prefixa (``config_status``) e o ``plugin`` retira o prefixo
    antes de chamar ``dispatch`` — a lógica de roteamento fica byte-a-byte idêntica.

O ``_TOOL_SCHEMAS`` abaixo é o dict LITERAL do fonte (byte-a-byte, incluindo os antigos
valores ``config-mcp.*``/``config-mcp:*``); logo após a definição, um passo determinístico
reescreve APENAS os 2 campos ``capability``/``required_scope`` (adaptação exigida) — os
demais campos (description/schema/resource_type/data_domain) permanecem intocados.
"""

from __future__ import annotations

from typing import Any

from .db.store import ConfigStore
from .tools import (
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

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "config"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <domain>:<tipo>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Leituras usam :read; mutações :write.
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
        "description": (
            "Remove (soft-delete) uma credencial do store central por namespace e chave; "
            "retorna se havia uma linha viva (idempotente)."
        ),
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

# ── Adaptação de namespace (strangler): reescreve SO os 2 campos exigidos ──────
# capability: ``config-mcp.<op>`` → ``devteam-mcp.config_<op>`` (id estável do server
# consolidado). required_scope: ``config-mcp:<res>:<ação>`` → ``config:<res>:<ação>``
# (dropa o prefixo de namespace antigo; least-privilege por-tool preservado).
for _op, _meta_entry in _TOOL_SCHEMAS.items():
    _meta_entry["capability"] = f"devteam-mcp.{DOMAIN}_{_op}"
    _meta_entry["required_scope"] = _meta_entry["required_scope"].replace("config-mcp:", f"{DOMAIN}:", 1)


# ── Dispatcher ────────────────────────────────────────────────────────────────
# Tools sem store nem tenant (status/health + sysinfo compute-only) são despachadas
# sem abrir sessão de tenant (dispatch storeless). As demais recebem um ConfigStore
# já ligado ao pool do tenant (resolvido dos claims do inner token — INV-3).
_STORELESS_TOOLS: frozenset[str] = frozenset({"status", "get_physical_info"})


async def dispatch_storeless(name: str) -> dict[str, Any]:
    """Despacha as tools que não tocam o store (status/sysinfo). Async por uniformidade."""
    if name == "status":
        return {"status": "ok", "service": "config-mcp", "tools": len(_TOOL_SCHEMAS)}
    if name == "get_physical_info":
        return await get_physical_info()
    raise KeyError(name)


async def dispatch(name: str, args: dict[str, Any], store: ConfigStore) -> dict[str, Any]:
    """Despacha (async) para a tool ligada ao store do tenant. tenant_id é injetado
    pelo PEP nos args a partir das claims (INV-3) e consumido pelas tools tenants.*."""
    # ── Credentials ───────────────────────────────────────────────────────── #
    if name == "get_credential":
        return await get_credential(store, namespace=args["namespace"], key=args["key"])
    if name == "set_credential":
        return await set_credential(
            store,
            namespace=args["namespace"],
            key=args["key"],
            value=args["value"],
            description=args.get("description"),
        )
    if name == "set_credential_secure":
        return await set_credential_secure(store, namespace=args["namespace"], key=args["key"])
    if name == "list_credentials":
        return await list_credentials(store, namespace=args.get("namespace"))
    if name == "delete_credential":
        return await delete_credential(store, namespace=args["namespace"], key=args["key"])
    # ── Env ───────────────────────────────────────────────────────────────── #
    if name == "get_env_config":
        return await get_env_config(
            store,
            environment=args["environment"],
            key_pattern=args.get("key_pattern"),
            limit=args.get("limit", 50),
        )
    if name == "set_env_var":
        return await set_env_var(store, environment=args["environment"], key=args["key"], value=args["value"])
    if name == "list_environments":
        return await list_environments(store)
    if name == "sync_env_file":
        return await sync_env_file(
            store,
            target_path=args["target_path"],
            environment=args["environment"],
            merge=args.get("merge", True),
        )
    if name == "read_env_file":
        return await read_env_file(store, path=args["path"], key_filter=args.get("key_filter"))
    if name == "audit_env_files":
        return await audit_env_files(
            store,
            directory=args["directory"],
            include_pattern=args.get("include_pattern", ".env*"),
            check_store=args.get("check_store", True),
        )
    if name == "redact_env_secrets":
        return await redact_env_secrets(
            store,
            paths=args["paths"],
            keys=args.get("keys"),
            auto_detect=args.get("auto_detect", True),
            dry_run=args.get("dry_run", False),
        )
    if name == "push_env_to_store":
        return await push_env_to_store(
            store,
            path=args["path"],
            environment=args["environment"],
            overwrite=args.get("overwrite", False),
            secrets_only=args.get("secrets_only", False),
        )
    # ── Workspace ─────────────────────────────────────────────────────────── #
    if name == "get_workspace_config":
        return await get_workspace_config(store, key=args.get("key"))
    if name == "set_workspace_config":
        return await set_workspace_config(
            store,
            key=args["key"],
            value=args["value"],
            create_dir=args.get("create_dir", False),
        )
    if name == "list_workspace_config":
        return await list_workspace_config(store)
    # ── Tenants (tenant_id das claims — INV-3) ─────────────────────────────── #
    if name == "get_tenant_config":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"error": "missing_tenant", "hint": "tenant_id resolvido das claims do token."}
        return await get_tenant_config(
            store,
            tenant_id=tenant_id,
            key_pattern=args.get("key_pattern"),
            limit=args.get("limit", 50),
        )
    if name == "set_tenant_config":
        tenant_id = args.get("tenant_id")
        if not tenant_id:
            return {"error": "missing_tenant", "hint": "tenant_id resolvido das claims do token."}
        return await set_tenant_config(store, tenant_id=tenant_id, key=args["key"], value=args["value"])
    if name == "list_tenants":
        return await list_tenants(store)
    if name == "get_session_tenant_config":
        return await get_session_tenant_config(store)

    raise KeyError(name)
