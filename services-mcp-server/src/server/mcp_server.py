"""Servidor MCP services — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:services-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3). O tenant seleciona o banco do tenant: cada chamada abre
     uma sessão tenant-scoped (`for_tenant`) e instancia um `ServiceStore` sobre ela.
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: services-mcp é **stateful** (registry de serviços), migrado 100% para o ORM
canônico (`platform_database.orm`), **tenant-scoped e dual-db** (credencial-zero,
ORM-H-12). Não há mais store global: cada chamada resolve o tenant dos claims, abre uma
sessão (`for_tenant`) e instancia um `ServiceStore`. `orm.configure(settings)` registra a
fonte admin (ADMIN_DB_*) usada para resolver o tenant → credencial do seu banco.

Tools (32):
  Registry (5):   register_service, get_service, list_services, update_service, unregister_service
  PortMap (2):    get_port_map, find_by_port
  Discovery (4):  scan_docker, scan_processes, check_health, check_all_health
  Composite (3):  service_status, list_environments, reload_service
  Gateway (3):    get_gateway_map, update_service_gateway, sync_registry
  Launch (2):     launch_service, stop_service
  Env (5):        read_env_file, set_env_var, sync_service_urls, audit_env_files, redact_env_secrets
  Infra (3):      register_infra, scan_infra, sync_infra_env
  Brokers (3):    kafka_status, redis_status, sync_broker_urls
  Logs (2):       get_service_logs, search_logs
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
from platform_database import close_tenant_pools
from platform_database.orm import configure, for_tenant
from platform_database.orm.dialects import dialect_for_pool
from platform_database.tenant_resolver import get_pool_for_tenant

from ..config.logging import configure_logging
from ..config.settings import ServicesSettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import ServiceStore
from ..tools import (
    audit_env_files,
    check_all_health,
    check_health,
    find_by_port,
    get_gateway_map,
    get_port_map,
    get_service,
    get_service_logs,
    kafka_status,
    launch_service,
    list_environments,
    list_services,
    read_env_file,
    redact_env_secrets,
    redis_status,
    register_infra,
    register_service,
    reload_service,
    scan_docker,
    scan_infra,
    scan_processes,
    search_logs,
    service_status,
    set_env_var,
    stop_service,
    sync_broker_urls,
    sync_infra_env,
    sync_registry,
    sync_service_urls,
    unregister_service,
    update_service,
    update_service_gateway,
)

_log = logging.getLogger(__name__)

# ── Escopo mínimo por ferramenta (least privilege) ─────────────────────────── #
# read  = consulta/descoberta (não muta estado do registry nem do host)
# write = mutação (registro, launch/stop, edição de .env, sync, reload)
SCOPE_FOR_TOOL: dict[str, str] = {
    # Registry
    "register_service": "services:write",
    "get_service": "services:read",
    "list_services": "services:read",
    "update_service": "services:write",
    "unregister_service": "services:write",  # deregister
    # PortMap
    "get_port_map": "services:read",
    "find_by_port": "services:read",
    # Discovery
    "scan_docker": "services:read",
    "scan_processes": "services:read",
    "check_health": "services:read",
    "check_all_health": "services:read",
    # Composite
    "service_status": "services:read",
    "list_environments": "services:read",
    # reload_service é SENSÍVEL: reinicia/mata o serviço (restart) → exige services:write.
    "reload_service": "services:write",
    # Gateway
    "get_gateway_map": "services:read",
    "update_service_gateway": "services:write",  # configure
    "sync_registry": "services:write",
    # Launch
    "launch_service": "services:write",
    "stop_service": "services:write",
    # Env (edições de arquivo .env são mutações)
    "read_env_file": "services:read",
    "set_env_var": "services:write",  # configure
    "sync_service_urls": "services:write",
    "audit_env_files": "services:read",
    "redact_env_secrets": "services:write",
    # Infra
    "register_infra": "services:write",
    "scan_infra": "services:read",
    "sync_infra_env": "services:write",
    # Brokers
    "kafka_status": "services:read",
    "redis_status": "services:read",
    "sync_broker_urls": "services:write",
    # Logs
    "get_service_logs": "services:read",
    "search_logs": "services:read",
}

# #
# Schemas                                                                      #
# #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # Registry  #
    "register_service": {
        "description": (
            "Registraou atualizaum servico no registry local. "
            "Se o servico ja existir, atualizaos campos fornecidos. "
            "Retornaaction=created ou action=updated."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome unico do servico."},
                "host": {
                    "type": "string",
                    "description": "Host onde o servico roda. Default: localhost.",
                    "default": "localhost",
                },
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "PortaTCP do servico.",
                },
                "url": {
                    "type": "string",
                    "description": "URL base do servico (ex: http://localhost:8080).",
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "docker",
                        "process",
                        "remote",
                        "unknown",
                        "mysql",
                        "mariadb",
                        "postgres",
                        "redis",
                        "kafka",
                        "mongodb",
                    ],
                    "description": "Tipo do servico. Default: unknown.",
                    "default": "unknown",
                },
                "environment": {
                    "type": "string",
                    "enum": ["local", "dev", "hml", "prod"],
                    "description": "Ambiente do servico. Default: local.",
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
                    "description": "Tags paraclassificacaoo.",
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Metadados extras (chave-valor livre).",
                },
                "runtime": {
                    "type": "string",
                    "description": "Runtime do servico: uvicorn, gunicorn, node, java, docker, etc.",
                },
                "deploy_mode": {
                    "type": "string",
                    "enum": ["asgi", "wsgi", "node", "jvm", "proxy", "docker", "script", "unknown"],
                    "description": "Modo de deploy derivado do runtime.",
                },
                "os_name": {
                    "type": "string",
                    "description": "Sistema operacional: linux, windows, darwin.",
                },
                "os_release": {
                    "type": "string",
                    "description": "Versao do OS/kernel (ex: 5.15.0-78-generic).",
                },
                "hostname": {
                    "type": "string",
                    "description": "Hostname do container ou da maquina.",
                },
            },
            "required": ["name", "port"],
            "additionalProperties": False,
        },
    },
    "get_service": {
        "description": "Retornaos dados de um servico pelo nome.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "list_services": {
        "description": (
            "Lista servicos registrados. "
            "Suporta filtros por environment, type, status, tag, runtime e deploy_mode."
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
                    "enum": [
                        "docker",
                        "process",
                        "remote",
                        "unknown",
                        "mysql",
                        "mariadb",
                        "postgres",
                        "redis",
                        "kafka",
                        "mongodb",
                    ],
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
                "runtime": {
                    "type": "string",
                    "description": "Filtrar por runtime (ex: uvicorn, gunicorn, node, docker).",
                },
                "deploy_mode": {
                    "type": "string",
                    "enum": ["asgi", "wsgi", "node", "jvm", "proxy", "docker", "script", "unknown"],
                    "description": "Filtrar por modo de deploy.",
                },
            },
            "additionalProperties": False,
        },
    },
    "update_service": {
        "description": (
            "Atualizacampos de um servico existente. Pelo menos um campo deve ser informado alem do name."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico aatualizar."},
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
        "description": (
            "Remove (soft-delete) um servico do registry pelo nome; some das leituras ativas "
            "e um novo registro reativa a linha."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico aremover."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    # PortMap  #
    "get_port_map": {
        "description": (
            "Retornamapade portaâ†’ servico paratodos os servicos registrados com porta. "
            "Ãštil paradetectar conflitos de porta."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "find_by_port": {
        "description": "Encontrao servico registrado em umaportaespecifica.",
        "schema": {
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "PortaTCP aconsultar.",
                },
            },
            "required": ["port"],
            "additionalProperties": False,
        },
    },
    # Discovery  #
    "scan_docker": {
        "description": (
            "Executa`docker ps` e sincronizacontainers em execucaoo no registry. "
            "Requer Docker instalado e acessivel no PATH."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 60,
                    "description": "Timeout em segundos parao comando docker. Default: 10.",
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
    },
    "scan_processes": {
        "description": (
            "Usapsutil paralistar processos em LISTEN. Retornalistade processos com pid, nome e porta."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "min_port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "Portaminimaaincluir. Default: 1024.",
                    "default": 1024,
                },
            },
            "additionalProperties": False,
        },
    },
    "check_health": {
        "description": (
            "RealizaHTTP GET no health endpoint de um servico registrado. "
            "Atualizalast_check_at e last_check_ok no registry."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico."},
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
            "Verificasaude de todos os servicos com health_path definido. "
            "Atualizastatus automaticamente: healthyâ†’running, unhealthyâ†’stopped."
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
    # Composite  #
    "service_status": {
        "description": (
            "Retornadados do servico + health check em umaunicachamada. "
            "overall_status: healthy | unhealthy | unknown."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico."},
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
            "Agrupaservicos por environment e retornacontagens. "
            "Mostratotal/running/stopped/unknown por ambiente."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "reload_service": {
        "description": (
            "Recarrega/reiniciaum servico registrado. "
            "Estrategiaautomaticapor tipo: "
            "docker â†’ `docker restart <name>` | "
            "process â†’ mataprocesso naporta(esperareinicio pelo process manager) | "
            "remote â†’ POST em /reload ou /actuator/restart | "
            "unknown â†’ re-verificahealth. "
            "Aguardawait_seconds e faz health check automatico apos o reload."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico arecarregar."},
                "wait_seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 60,
                    "default": 3.0,
                    "description": "Segundos paraaguardar antes de verificar health. Default: 3.",
                },
                "health_timeout": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 30,
                    "default": 5.0,
                    "description": "Timeout do health check pos-reload em segundos. Default: 5.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    # Gateway  #
    "get_gateway_map": {
        "description": (
            "Retornao MAPPING_GATEWAY  -  mapade todos os servicos com URLs internae externa. "
            "Paracadaservico informa: external_url (localhost:porta), internal_url (container:porta), "
            "active_url (qual usar no contexto atual), context (docker ou local) e status. "
            "Use pararotear chamadas entre servicos corretamente em Docker e uvicorn."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "update_service_gateway": {
        "description": (
            "Atualizaas URLs de gateway (internal_url e external_url) de um servico no banco. "
            "Se internal_url naoo fornecida, derivado nome do container. "
            "Se external_url naoo fornecida, derivade host:port. "
            "Com probe=true, testaas URLs antes de salvar e marcao status."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico."},
                "internal_url": {
                    "type": "string",
                    "description": "URL internaDocker (ex: http://container-name:7100).",
                },
                "external_url": {
                    "type": "string",
                    "description": "URL externaacessivel do host (ex: http://localhost:27101).",
                },
                "host": {"type": "string", "description": "Host externo."},
                "port": {"type": "integer", "description": "Portaexterna."},
                "probe": {
                    "type": "boolean",
                    "default": True,
                    "description": "Testar URLs antes de salvar.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "sync_registry": {
        "description": (
            "Scan completo de descoberta -  sincronizabanco e MAPPING_GATEWAY. "
            "Executa: (1) scan Docker (docker ps) descobrindo containers e portas; "
            "(2) scan de portas nos ranges configurados procurando servicos HTTP; "
            "(3) scan por nomes de servicos viaDocker DNS ou localhost. "
            "Chamado automaticamente no startup do services-mcp."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "port_ranges": {
                    "type": "string",
                    "description": "Ranges de portaseparados por virgula. Ex: '8000-8100,27100-27130'. Default: PORT_SCAN_RANGES env ou '8000-8100'.",  # noqa: E501
                },
                "service_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Listade nomes de servicos pararesolver viaDNS. Default: SERVICE_NAMES env.",  # noqa: E501
                },
                "include_docker": {
                    "type": "boolean",
                    "default": True,
                    "description": "Incluir scan Docker (docker ps).",
                },
                "probe_health": {
                    "type": "boolean",
                    "default": True,
                    "description": "Probar /health em cadaservico encontrado.",
                },
                "docker_timeout": {
                    "type": "integer",
                    "default": 10,
                    "description": "Timeout em segundos paradocker ps.",
                },
            },
            "additionalProperties": False,
        },
    },
    # Launch  #
    "launch_service": {
        "description": (
            "Sobe um servico viauvicorn, docker run ou docker-compose e registrano registry. "
            "Apos o start faz polling no health_path ate wait_timeout segundos. "
            "Modos: 'uvicorn' (requer app), 'docker' (requer image), 'docker-compose' (usacompose_file/compose_service). "  # noqa: E501
            "Retorna: started, healthy, ready_in_ms, attempts, external_url, pid/container_id."
        ),
        "schema": {
            "type": "object",
            "required": ["name", "mode", "port"],
            "additionalProperties": False,
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nome do servico (usado no registry e como container name).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["uvicorn", "docker", "docker-compose"],
                    "description": "Modo de start.",
                },
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "Portado host.",
                },
                "app": {
                    "type": "string",
                    "description": "uvicorn: caminho ASGI (ex: 'mypackage.main:app').",
                },
                "host": {
                    "type": "string",
                    "default": "localhost",
                    "description": "Host parauvicorn. Default: localhost.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Diretorio de trabalho (uvicorn / docker-compose).",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Args extras passados ao comando.",
                },
                "env_vars": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Variaveis de ambiente.",
                },
                "image": {
                    "type": "string",
                    "description": "docker: imagem Docker (ex: 'nginx:latest').",
                },
                "container_port": {
                    "type": "integer",
                    "description": "docker: portainternado container. Default: igual ao port.",
                },
                "container_name": {
                    "type": "string",
                    "description": "docker: nome do container. Default: igual ao name.",
                },
                "compose_file": {
                    "type": "string",
                    "description": "docker-compose: path parao compose file. Default: docker-compose.yml.",
                },
                "compose_service": {
                    "type": "string",
                    "description": "docker-compose: nome do servico no compose. Default: igual ao name.",
                },
                "health_path": {
                    "type": "string",
                    "default": "/v1/health",
                    "description": "Path do health check. Default: /v1/health.",
                },
                "environment": {
                    "type": "string",
                    "enum": ["local", "dev", "hml", "prod"],
                    "default": "local",
                    "description": "Ambiente pararegistro.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags parao servico.",
                },
                "wait_timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "default": 30,
                    "description": "Segundos aguardando o servico responder. Default: 30.",
                },
                "detach": {
                    "type": "boolean",
                    "default": True,
                    "description": "Rodar em background. Default: true.",
                },
            },
        },
    },
    "stop_service": {
        "description": (
            "Paraum servico registrado. "
            "Detectaautomaticamente o tipo: docker/docker-compose â†' docker stop; process/uvicorn â†' SIGTERM no PID. "  # noqa: E501
            "Atualizastatus=stopped no registry apos parar."
        ),
        "schema": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Nome do servico aparar."},
                "mode": {
                    "type": "string",
                    "enum": ["docker", "docker-compose", "process"],
                    "description": "Forcar tipo de stop. Se omitido, detectapelo registro.",
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 120,
                    "default": 10,
                    "description": "Timeout em segundos paradocker stop. Default: 10.",
                },
            },
        },
    },
    # Env  #
    "read_env_file": {
        "description": (
            "Le um arquivo .env e retornaas variaveis como dict. "
            "Suportafiltro por substring no nome das chaves."
        ),
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho absoluto ou relativo do arquivo .env.",
                },
                "key_filter": {
                    "type": "string",
                    "description": "Substring parafiltrar chaves (case-insensitive). Ex: 'URL' retornaapenas vars URL_*.",  # noqa: E501
                },
            },
        },
    },
    "set_env_var": {
        "description": (
            "Define ou atualizaumavariavel em um arquivo .env. "
            "Preservacomentarios, ordem e formatação existente. "
            "Se avariavel naoo existir, adicionaao final (create_if_missing=true)."
        ),
        "schema": {
            "type": "object",
            "required": ["path", "key", "value"],
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo .env."},
                "key": {"type": "string", "description": "Nome davariavel. Ex: URL_ADMIN."},
                "value": {"type": "string", "description": "Novo valor."},
                "create_if_missing": {
                    "type": "boolean",
                    "default": True,
                    "description": "Criar avariavel se naoo existir. Default: true.",
                },
                "comment": {
                    "type": "string",
                    "description": "Comentario aadicionar acimadavariavel (so quando criando).",
                },
            },
        },
    },
    "sync_service_urls": {
        "description": (
            "Sincronizavariaveis URL_* de um arquivo .env com as URLs registradas no registry. "
            "ParacadaURL_<NAME>, buscao servico 'name' ou 'platform-name' no registry e atualizao valor. "
            "Preservao path existente daURL (ex: /api/v1) amenos que url_suffix sejainformado. "
            "Use url_map paramapeamentos explicitos. Use dry_run=true parasimular sem alterar."
        ),
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo .env aatualizar."},
                "url_map": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": 'Mapeamento explicito {ENV_VAR: service_name}. Ex: {"URL_ADMIN": "platform-admin"}.',  # noqa: E501
                },
                "url_suffix": {
                    "type": "string",
                    "default": "",
                    "description": "Sufixo de path aforcar. Ex: '/api/v1'. Se vazio, preservao path atual.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Se true, apenas simulaas mudancas sem alterar o arquivo.",
                },
            },
        },
    },
    "audit_env_files": {
        "description": (
            "Escaneia todos os arquivos .env.* de um diretorio e reporta problemas. "
            "Detecta: secrets hardcoded (JWT_SECRET_KEY, DB_PASSWORD, TOKEN, etc), "
            "URLs que nao batem com o registry, vars ausentes em alguns perfis, "
            "arquivos fora do padrao canonico (local-dev, local-hml, cloud-dev, cloud-hml, cloud-prod). "
            "Use antes de redact_env_secrets para ver o que precisa ser corrigido."
        ),
        "schema": {
            "type": "object",
            "required": ["directory"],
            "additionalProperties": False,
            "properties": {
                "directory": {"type": "string", "description": "Caminho do diretorio a escanear."},
                "include_pattern": {
                    "type": "string",
                    "default": ".env*",
                    "description": "Glob para os arquivos. Default: .env*.",
                },
                "check_registry_urls": {
                    "type": "boolean",
                    "default": True,
                    "description": "Verificar URLs contra o registry. Default: true.",
                },
            },
        },
    },
    "redact_env_secrets": {
        "description": (
            "Substitui valores hardcoded de secrets por referencias ${VAR_NAME} em arquivos .env. "
            "Ex: JWT_SECRET_KEY=XrDsC... vira JWT_SECRET_KEY=${JWT_SECRET_KEY}. "
            "O valor real passa a vir do shell, CI/CD ou k8s secret. "
            "Use dry_run=true para simular antes de aplicar."
        ),
        "schema": {
            "type": "object",
            "required": ["paths"],
            "additionalProperties": False,
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de caminhos dos arquivos .env a processar.",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Chaves explicitas a redact (ex: [JWT_SECRET_KEY]). Se omitido, usa auto_detect.",  # noqa: E501
                },
                "auto_detect": {
                    "type": "boolean",
                    "default": True,
                    "description": "Detectar automaticamente vars *KEY, *SECRET, *PASSWORD, *TOKEN. Default: true.",  # noqa: E501
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Simular sem alterar arquivos. Default: false.",
                },
            },
        },
    },
    # -- Infra (MySQL / Postgres / Redis / Kafka) -------------------------------- #
    "register_infra": {
        "description": (
            "Registra um servico de infraestrutura no registry com defaults inteligentes por tipo. "
            "Tipos suportados: mysql, mariadb, postgres, redis, kafka, mongodb. "
            "Para Kafka, use host_port para a porta EXTERNAL (ex: 9094) acessivel do host."
        ),
        "schema": {
            "type": "object",
            "required": ["name", "kind"],
            "additionalProperties": False,
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nome unico no registry (ex: mysql, redis, kafka).",
                },
                "kind": {
                    "type": "string",
                    "enum": ["mysql", "mariadb", "postgres", "redis", "kafka", "mongodb"],
                    "description": "Tipo de infraestrutura.",
                },
                "host": {
                    "type": "string",
                    "default": "localhost",
                    "description": "Host. Default: localhost.",
                },
                "port": {
                    "type": "integer",
                    "description": "Porta. Se omitido, usa o default do tipo (mysql:3306, redis:6379, kafka:9092).",  # noqa: E501
                },
                "host_port": {
                    "type": "integer",
                    "description": "Porta mapeada no host para acesso externo (Kafka EXTERNAL listener). Ex: 9094.",  # noqa: E501
                },
                "environment": {
                    "type": "string",
                    "default": "local",
                    "description": "Ambiente. Default: local.",
                },
                "container_name": {
                    "type": "string",
                    "description": "Nome do container Docker, se aplicavel.",
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Metadados extras livres.",
                },
            },
        },
    },
    "scan_infra": {
        "description": (
            "Varre containers Docker em execucao e registra automaticamente os de infraestrutura "
            "(mysql, mariadb, postgres, redis, kafka, mongodb) detectados pelo nome da imagem. "
            "Para Kafka, usa a porta EXTERNAL (9094) se disponivel. "
            "Nao afeta containers de aplicacao (plataform-*, mcp-*, etc)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "timeout": {
                    "type": "integer",
                    "default": 10,
                    "description": "Timeout do docker ps em segundos. Default: 10.",
                },
                "environment": {
                    "type": "string",
                    "default": "local",
                    "description": "Ambiente a marcar nos registros. Default: local.",
                },
            },
        },
    },
    "sync_infra_env": {
        "description": (
            "Atualiza TODAS as vars de conexao de infraestrutura num arquivo .env a partir do registry. "
            "DB: DB_HOST, DB_PORT, ADMIN_DB_HOST, ADMIN_DB_PORT (detecta DB_ENGINE automaticamente). "
            "Redis: REDIS_URL, RATE_LIMIT_STORAGE_URI, CACHE_URL, CELERY_BROKER_URL, etc. "
            "Kafka: KAFKA_BOOTSTRAP_SERVERS (usa porta EXTERNAL/host_port se registrada). "
            "Postgres: DATABASE_URL (reconstroi DSN). "
            "Use dry_run=true para simular antes de aplicar."
        ),
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo .env a atualizar.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Simular sem alterar o arquivo. Default: false.",
                },
                "db_kind": {
                    "type": "string",
                    "enum": ["mysql", "mariadb", "postgres"],
                    "description": "Forca o tipo de DB se DB_ENGINE nao estiver no arquivo. Default: mysql.",
                },
            },
        },
    },
    # -- Brokers (Kafka / Redis) ---------------------------------------------- #
    "kafka_status": {
        "description": (
            "Verifica conectividade TCP com o broker Kafka. "
            "Se bootstrap_servers nao for passado, busca no registry (type='kafka' ou nome 'kafka'/'platform-kafka'). "  # noqa: E501
            "Retorna lista de brokers com reachable=true/false e latencia em ms."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "bootstrap_servers": {
                    "type": "string",
                    "description": "Broker(s) Kafka: 'host:port' ou 'h1:p1,h2:p2'. Se omitido, usa registry.",
                },
            },
        },
    },
    "redis_status": {
        "description": (
            "Verifica conectividade com o Redis via TCP + RESP PING. "
            "Se url nao for passado, busca no registry (type='redis'/'cache'). "
            "Retorna reachable, latencia_ms e resposta do PING."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL Redis: redis://host:port/db ou host:port. Se omitido, usa registry.",
                },
            },
        },
    },
    "sync_broker_urls": {
        "description": (
            "Atualiza vars de conexao de Kafka e Redis num arquivo .env a partir do registry. "
            "Vars tratadas: KAFKA_BOOTSTRAP_SERVERS, REDIS_URL, REDIS_HOST, REDIS_URI, "
            "RATE_LIMIT_STORAGE_URI, CACHE_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND. "
            "Preserva o /db da URL Redis existente. Use dry_run=true para simular."
        ),
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho absoluto do arquivo .env a atualizar.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Simular sem alterar o arquivo. Default: false.",
                },
            },
        },
    },
    # -- Logs ------------------------------------------------------------------- #
    "get_service_logs": {
        "description": (
            "Retorna as ultimas N linhas de log de um servico registrado. "
            "Suporta Docker (container_name), arquivo de log (metadata.log_path) e systemd/journald (Linux). "
            "since: '30m', '1h', '2h30m', '5s' ou timestamp ISO 8601. "
            "grep: filtro regex case-insensitive nas linhas retornadas. "
            "timestamps: inclui timestamp Docker em cada linha."
        ),
        "schema": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Nome do servico no registry."},
                "lines": {
                    "type": "integer",
                    "default": 100,
                    "description": "Numero de linhas a retornar. Default: 100.",
                },
                "since": {
                    "type": "string",
                    "description": "Janela de tempo: '30m', '1h', '5s' ou ISO 8601. Opcional.",
                },
                "grep": {
                    "type": "string",
                    "description": "Filtro regex case-insensitive nas linhas. Opcional.",
                },
                "timestamps": {
                    "type": "boolean",
                    "default": False,
                    "description": "Inclui timestamp Docker. Default: false.",
                },
            },
        },
    },
    "search_logs": {
        "description": (
            "Busca por padrao regex nos logs recentes de um servico. "
            "Varre as ultimas N linhas e retorna apenas as que batem com o padrao. "
            "lines: quantas linhas vasculhar antes de filtrar (default 500). "
            "since: restringe a janela temporal (opcional)."
        ),
        "schema": {
            "type": "object",
            "required": ["name", "pattern"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Nome do servico no registry."},
                "pattern": {
                    "type": "string",
                    "description": "Padrao regex a buscar nos logs (case-insensitive).",
                },
                "lines": {
                    "type": "integer",
                    "default": 500,
                    "description": "Janela de linhas a vasculhar. Default: 500.",
                },
                "since": {
                    "type": "string",
                    "description": "Janela de tempo: '30m', '1h', '5s' ou ISO 8601. Opcional.",
                },
            },
        },
    },
}


# Garante que todo tool declarado tem um escopo mínimo mapeado (least privilege).
assert set(_TOOL_SCHEMAS.keys()) == set(SCOPE_FOR_TOOL.keys()), (  # noqa: S101 — invariante de config
    "SCOPE_FOR_TOOL deve cobrir exatamente as tools de _TOOL_SCHEMAS: "
    f"faltam={set(_TOOL_SCHEMAS) - set(SCOPE_FOR_TOOL)} "
    f"sobram={set(SCOPE_FOR_TOOL) - set(_TOOL_SCHEMAS)}"
)

# ── Policy metadata por tool (STD-MCP-001 CI-2) ───────────────────────────────
# O gateway NÃO deriva policy por nome: cada tool declara, além de description/
# schema, os 4 campos de política que são emitidos em /mcp/tools/list:
#   capability     — id estável <namespace>.<tool>
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# A ação (read|write) é derivada do SCOPE_FOR_TOOL já existente (least privilege).
NAMESPACE = "services-mcp"

# resource_type por tool (mesma taxonomia usada no gateway/README).
_RESOURCE_TYPE: dict[str, str] = {
    # Registry / Composite tocam o recurso lógico "service"
    "register_service": "service",
    "get_service": "service",
    "list_services": "service",
    "update_service": "service",
    "unregister_service": "service",
    "service_status": "service",
    "list_environments": "service",
    "reload_service": "service",
    # PortMap
    "get_port_map": "portmap",
    "find_by_port": "portmap",
    # Discovery
    "scan_docker": "discovery",
    "scan_processes": "discovery",
    "check_health": "discovery",
    "check_all_health": "discovery",
    # Gateway
    "get_gateway_map": "gateway",
    "update_service_gateway": "gateway",
    "sync_registry": "gateway",
    # Launch (lifecycle)
    "launch_service": "lifecycle",
    "stop_service": "lifecycle",
    # Env (configuration)
    "read_env_file": "env",
    "set_env_var": "env",
    "sync_service_urls": "env",
    "audit_env_files": "env",
    "redact_env_secrets": "env",
    # Infra
    "register_infra": "infra",
    "scan_infra": "infra",
    "sync_infra_env": "infra",
    # Brokers
    "kafka_status": "broker",
    "redis_status": "broker",
    "sync_broker_urls": "broker",
    # Logs
    "get_service_logs": "logs",
    "search_logs": "logs",
}

# data_domain por tool.
_DATA_DOMAIN: dict[str, str] = {
    **{
        t: "configuration"
        for t in (
            "read_env_file",
            "set_env_var",
            "sync_service_urls",
            "audit_env_files",
            "redact_env_secrets",
        )
    },  # noqa: E501
    **{t: "observability" for t in ("get_service_logs", "search_logs")},
}


def _action_for(tool: str) -> str:
    """read|write derivado do least-privilege scope já mapeado (SCOPE_FOR_TOOL)."""
    return "write" if SCOPE_FOR_TOOL[tool].endswith(":write") else "read"


# Injeta os 4 campos de policy em cada meta de _TOOL_SCHEMAS (o gateway lê estes
# campos em /mcp/tools/list). resource_type default = "service"; data_domain
# default = "infrastructure".
for _tool, _meta in _TOOL_SCHEMAS.items():
    _rtype = _RESOURCE_TYPE.get(_tool, "service")
    _meta["capability"] = f"{NAMESPACE}.{_tool}"
    _meta["required_scope"] = f"{NAMESPACE}:{_rtype}:{_action_for(_tool)}"
    _meta["resource_type"] = _rtype
    _meta["data_domain"] = _DATA_DOMAIN.get(_tool, "infrastructure")

# Campos de policy repassados no /mcp/tools/list.
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")

# Tools encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless). services-mcp
# não expõe tool pública/tokenless: TODA execução exige inner token válido.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que nunca devem sair pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: ServicesSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:services-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:services-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: ServicesSettings, tenant_id: str) -> None:
    """Garante a tabela `services` no banco do tenant (uma vez por processo). O engine é o
    do dialeto do pool resolvido — é o ponto que faz o mesmo código servir o dual-db."""
    if tenant_id in _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if tenant_id in _SCHEMA_READY:
            return
        # Mesmo pool cacheado que o for_tenant usará (registry por TenantDBConfig).
        pool = await get_pool_for_tenant(settings, tenant_id, strict=True)
        await ensure_schema(pool, engine=dialect_for_pool(pool).name)
        _SCHEMA_READY.add(tenant_id)


async def _run_tool(
    name: str, arguments: dict[str, Any], settings: ServicesSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        store = ServiceStore(session)
        return await _dispatch(name, arguments, store, settings)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: ServicesSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="services-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "services-mcp", "tools": len(_TOOL_SCHEMAS)}

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
    async def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Toda tool do services toca estado do tenant → inner token obrigatório (não há
        # _EXEMPT_TOOLS). O tenant vem SEMPRE dos claims (SEC-035 / INV-3), nunca do arg.
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

        try:
            payload = await _run_tool(name, arguments, settings, str(tenant_id))
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    @app.on_event("shutdown")
    async def _close_pools() -> None:
        # Fecha os pools por-tenant no shutdown (registry compartilhado da lib).
        await close_tenant_pools()

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, ServicesSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    Não há mais store global: a persistência é tenant-scoped e resolvida por-request
    (credencial-zero). ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*)
    usada para resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast no boot (STD-SEC-001/004/006)
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info("services_mcp_ready tools=%d engine=%s", len(_TOOL_SCHEMAS), settings.DB_ENGINE)

    server: Server = Server("services-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). services-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "services-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
                    "(/mcp/tools/call) com o inner Twin Token — o tenant vem dos claims."
                ),
            }
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, http_app


# ── Dispatcher (stateful: store tenant-scoped + settings injetados nas tools) ──


async def _dispatch(
    name: str,
    args: dict[str, Any],
    store: ServiceStore,
    settings: ServicesSettings,
) -> dict:
    """Despacha a chamada para a tool (async). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Registry ──────────────────────────────────────────────────────────────
    if name == "register_service":
        return await register_service(
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
        return await get_service(store, name=args["name"])
    if name == "list_services":
        return await list_services(
            store,
            environment=args.get("environment"),
            tag=args.get("tag"),
            type=args.get("type"),
            status=args.get("status"),
            runtime=args.get("runtime"),
            deploy_mode=args.get("deploy_mode"),
        )
    if name == "update_service":
        update_args = {k: v for k, v in args.items() if k != "name"}
        return await update_service(store, name=args["name"], **update_args)
    if name == "unregister_service":
        return await unregister_service(store, name=args["name"])
    # PortMap  #
    if name == "get_port_map":
        return await get_port_map(store)
    if name == "find_by_port":
        return await find_by_port(store, port=args["port"])
    # Discovery  #
    if name == "scan_docker":
        return await scan_docker(store, timeout=args.get("timeout", settings.docker_timeout))
    if name == "scan_processes":
        return await scan_processes(store, min_port=args.get("min_port", 1024))
    if name == "check_health":
        return await check_health(
            store, name=args["name"], timeout=args.get("timeout", settings.health_timeout)
        )
    if name == "check_all_health":
        return await check_all_health(store, timeout=args.get("timeout", settings.health_timeout))
    # Composite  #
    if name == "service_status":
        return await service_status(
            store, name=args["name"], timeout=args.get("timeout", settings.health_timeout)
        )
    if name == "list_environments":
        return await list_environments(store)
    if name == "reload_service":
        return await reload_service(
            store,
            name=args["name"],
            wait_seconds=args.get("wait_seconds", 3.0),
            health_timeout=args.get("health_timeout", settings.health_timeout),
        )
    # Gateway  #
    if name == "get_gateway_map":
        return await get_gateway_map(store)
    if name == "update_service_gateway":
        return await update_service_gateway(
            store,
            name=args["name"],
            internal_url=args.get("internal_url"),
            external_url=args.get("external_url"),
            host=args.get("host"),
            port=args.get("port"),
            probe=args.get("probe", True),
        )
    if name == "sync_registry":
        return await sync_registry(
            store,
            port_ranges=args.get("port_ranges"),
            service_names=args.get("service_names"),
            include_docker=args.get("include_docker", True),
            probe_health=args.get("probe_health", True),
            docker_timeout=args.get("docker_timeout", 10),
        )
    # Launch  #
    if name == "launch_service":
        return await launch_service(
            store,
            name=args["name"],
            mode=args["mode"],
            port=args["port"],
            app=args.get("app"),
            host=args.get("host", "localhost"),
            cwd=args.get("cwd"),
            extra_args=args.get("extra_args"),
            env_vars=args.get("env_vars"),
            image=args.get("image"),
            container_port=args.get("container_port"),
            container_name=args.get("container_name"),
            compose_file=args.get("compose_file"),
            compose_service=args.get("compose_service"),
            health_path=args.get("health_path", "/v1/health"),
            environment=args.get("environment", "local"),
            tags=args.get("tags"),
            wait_timeout=args.get("wait_timeout", 30),
            detach=args.get("detach", True),
        )
    if name == "stop_service":
        return await stop_service(
            store,
            name=args["name"],
            mode=args.get("mode"),
            timeout=args.get("timeout", 10),
        )
    # Env  #
    if name == "read_env_file":
        return await read_env_file(store, path=args["path"], key_filter=args.get("key_filter"))
    if name == "set_env_var":
        return await set_env_var(
            store,
            path=args["path"],
            key=args["key"],
            value=args["value"],
            create_if_missing=args.get("create_if_missing", True),
            comment=args.get("comment"),
        )
    if name == "sync_service_urls":
        return await sync_service_urls(
            store,
            path=args["path"],
            url_map=args.get("url_map"),
            url_suffix=args.get("url_suffix", ""),
            dry_run=args.get("dry_run", False),
        )
    if name == "audit_env_files":
        return await audit_env_files(
            store,
            directory=args["directory"],
            include_pattern=args.get("include_pattern", ".env*"),
            check_registry_urls=args.get("check_registry_urls", True),
        )
    if name == "redact_env_secrets":
        return await redact_env_secrets(
            store,
            paths=args["paths"],
            keys=args.get("keys"),
            auto_detect=args.get("auto_detect", True),
            dry_run=args.get("dry_run", False),
        )
    # -- Infra ------------------------------------------------------------------
    if name == "register_infra":
        return await register_infra(
            store,
            name=args["name"],
            kind=args["kind"],
            host=args.get("host", "localhost"),
            port=args.get("port"),
            host_port=args.get("host_port"),
            environment=args.get("environment", "local"),
            container_name=args.get("container_name"),
            metadata=args.get("metadata"),
        )
    if name == "scan_infra":
        return await scan_infra(
            store,
            timeout=args.get("timeout", 10),
            environment=args.get("environment", "local"),
        )
    if name == "sync_infra_env":
        return await sync_infra_env(
            store,
            path=args["path"],
            dry_run=args.get("dry_run", False),
            db_kind=args.get("db_kind"),
        )
    # -- Brokers ----------------------------------------------------------------
    if name == "kafka_status":
        return await kafka_status(store, bootstrap_servers=args.get("bootstrap_servers"))
    if name == "redis_status":
        return await redis_status(store, url=args.get("url"))
    if name == "sync_broker_urls":
        return await sync_broker_urls(store, path=args["path"], dry_run=args.get("dry_run", False))
    # -- Logs -------------------------------------------------------------------
    if name == "get_service_logs":
        return await get_service_logs(
            store,
            name=args["name"],
            lines=args.get("lines", 100),
            since=args.get("since"),
            grep=args.get("grep"),
            timestamps=args.get("timestamps", False),
        )
    if name == "search_logs":
        return await search_logs(
            store,
            name=args["name"],
            pattern=args["pattern"],
            lines=args.get("lines", 500),
            since=args.get("since"),
        )

    raise KeyError(name)


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
