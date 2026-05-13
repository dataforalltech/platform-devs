"""Servidor MCP services  -  32 tools para registro e monitoramento de servicos.

Tools:
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

Streaming (HTTP sidecar):
  GET /v1/services/{name}/logs/stream?lines=50&grep=<pattern>&timestamps=false
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
    audit_env_files,
    check_all_health,
    check_health,
    find_by_port,
    get_gateway_map,
    get_port_map,
    get_service,
    get_service_logs,
    kafka_status,
    list_environments,
    list_services,
    launch_service,
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

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
# Schemas                                                                      #
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # â"€â"€ Registry â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
                        "docker", "process", "remote", "unknown",
                        "mysql", "mariadb", "postgres", "redis", "kafka", "mongodb",
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
                        "docker", "process", "remote", "unknown",
                        "mysql", "mariadb", "postgres", "redis", "kafka", "mongodb",
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
            "Atualizacampos de um servico existente. "
            "Pelo menos um campo deve ser informado alem do name."
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
        "description": "Remove um servico do registry.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do servico aremover."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    # â"€â"€ PortMap â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
    # â"€â"€ Discovery â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
            "Usapsutil paralistar processos em LISTEN. "
            "Retornalistade processos com pid, nome e porta."
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
    # â"€â"€ Composite â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
    # â"€â"€ Gateway â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
                    "description": "Ranges de portaseparados por virgula. Ex: '8000-8100,27100-27130'. Default: PORT_SCAN_RANGES env ou '8000-8100'.",
                },
                "service_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Listade nomes de servicos pararesolver viaDNS. Default: SERVICE_NAMES env.",
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
    # â"€â"€ Launch â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
    "launch_service": {
        "description": (
            "Sobe um servico viauvicorn, docker run ou docker-compose e registrano registry. "
            "Apos o start faz polling no health_path ate wait_timeout segundos. "
            "Modos: 'uvicorn' (requer app), 'docker' (requer image), 'docker-compose' (usacompose_file/compose_service). "
            "Retorna: started, healthy, ready_in_ms, attempts, external_url, pid/container_id."
        ),
        "schema": {
            "type": "object",
            "required": ["name", "mode", "port"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Nome do servico (usado no registry e como container name)."},
                "mode": {
                    "type": "string",
                    "enum": ["uvicorn", "docker", "docker-compose"],
                    "description": "Modo de start.",
                },
                "port": {"type": "integer", "minimum": 1, "maximum": 65535, "description": "Portado host."},
                "app": {"type": "string", "description": "uvicorn: caminho ASGI (ex: 'mypackage.main:app')."},
                "host": {"type": "string", "default": "localhost", "description": "Host parauvicorn. Default: localhost."},
                "cwd": {"type": "string", "description": "Diretorio de trabalho (uvicorn / docker-compose)."},
                "extra_args": {"type": "array", "items": {"type": "string"}, "description": "Args extras passados ao comando."},
                "env_vars": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Variaveis de ambiente."},
                "image": {"type": "string", "description": "docker: imagem Docker (ex: 'nginx:latest')."},
                "container_port": {"type": "integer", "description": "docker: portainternado container. Default: igual ao port."},
                "container_name": {"type": "string", "description": "docker: nome do container. Default: igual ao name."},
                "compose_file": {"type": "string", "description": "docker-compose: path parao compose file. Default: docker-compose.yml."},
                "compose_service": {"type": "string", "description": "docker-compose: nome do servico no compose. Default: igual ao name."},
                "health_path": {"type": "string", "default": "/v1/health", "description": "Path do health check. Default: /v1/health."},
                "environment": {
                    "type": "string",
                    "enum": ["local", "dev", "hml", "prod"],
                    "default": "local",
                    "description": "Ambiente pararegistro.",
                },
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags parao servico."},
                "wait_timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30, "description": "Segundos aguardando o servico responder. Default: 30."},
                "detach": {"type": "boolean", "default": True, "description": "Rodar em background. Default: true."},
            },
        },
    },
    "stop_service": {
        "description": (
            "Paraum servico registrado. "
            "Detectaautomaticamente o tipo: docker/docker-compose â†' docker stop; process/uvicorn â†' SIGTERM no PID. "
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
                "timeout": {"type": "integer", "minimum": 1, "maximum": 120, "default": 10, "description": "Timeout em segundos paradocker stop. Default: 10."},
            },
        },
    },
    # â"€â"€ Env â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
                "path": {"type": "string", "description": "Caminho absoluto ou relativo do arquivo .env."},
                "key_filter": {"type": "string", "description": "Substring parafiltrar chaves (case-insensitive). Ex: 'URL' retornaapenas vars URL_*."},
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
                "comment": {"type": "string", "description": "Comentario aadicionar acimadavariavel (so quando criando)."},
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
                    "description": "Mapeamento explicito {ENV_VAR: service_name}. Ex: {\"URL_ADMIN\": \"platform-admin\"}.",
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
                "include_pattern": {"type": "string", "default": ".env*", "description": "Glob para os arquivos. Default: .env*."},
                "check_registry_urls": {"type": "boolean", "default": True, "description": "Verificar URLs contra o registry. Default: true."},
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
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Lista de caminhos dos arquivos .env a processar."},
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Chaves explicitas a redact (ex: [JWT_SECRET_KEY]). Se omitido, usa auto_detect."},
                "auto_detect": {"type": "boolean", "default": True, "description": "Detectar automaticamente vars *KEY, *SECRET, *PASSWORD, *TOKEN. Default: true."},
                "dry_run": {"type": "boolean", "default": False, "description": "Simular sem alterar arquivos. Default: false."},
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
                "name": {"type": "string", "description": "Nome unico no registry (ex: mysql, redis, kafka)."},
                "kind": {
                    "type": "string",
                    "enum": ["mysql", "mariadb", "postgres", "redis", "kafka", "mongodb"],
                    "description": "Tipo de infraestrutura.",
                },
                "host": {"type": "string", "default": "localhost", "description": "Host. Default: localhost."},
                "port": {"type": "integer", "description": "Porta. Se omitido, usa o default do tipo (mysql:3306, redis:6379, kafka:9092)."},
                "host_port": {"type": "integer", "description": "Porta mapeada no host para acesso externo (Kafka EXTERNAL listener). Ex: 9094."},
                "environment": {"type": "string", "default": "local", "description": "Ambiente. Default: local."},
                "container_name": {"type": "string", "description": "Nome do container Docker, se aplicavel."},
                "metadata": {"type": "object", "additionalProperties": True, "description": "Metadados extras livres."},
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
                "timeout": {"type": "integer", "default": 10, "description": "Timeout do docker ps em segundos. Default: 10."},
                "environment": {"type": "string", "default": "local", "description": "Ambiente a marcar nos registros. Default: local."},
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
                "path": {"type": "string", "description": "Caminho absoluto do arquivo .env a atualizar."},
                "dry_run": {"type": "boolean", "default": False, "description": "Simular sem alterar o arquivo. Default: false."},
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
            "Se bootstrap_servers nao for passado, busca no registry (type='kafka' ou nome 'kafka'/'platform-kafka'). "
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
                "path": {"type": "string", "description": "Caminho absoluto do arquivo .env a atualizar."},
                "dry_run": {"type": "boolean", "default": False, "description": "Simular sem alterar o arquivo. Default: false."},
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
                "lines": {"type": "integer", "default": 100, "description": "Numero de linhas a retornar. Default: 100."},
                "since": {"type": "string", "description": "Janela de tempo: '30m', '1h', '5s' ou ISO 8601. Opcional."},
                "grep": {"type": "string", "description": "Filtro regex case-insensitive nas linhas. Opcional."},
                "timestamps": {"type": "boolean", "default": False, "description": "Inclui timestamp Docker. Default: false."},
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
                "pattern": {"type": "string", "description": "Padrao regex a buscar nos logs (case-insensitive)."},
                "lines": {"type": "integer", "default": 500, "description": "Janela de linhas a vasculhar. Default: 500."},
                "since": {"type": "string", "description": "Janela de tempo: '30m', '1h', '5s' ou ISO 8601. Opcional."},
            },
        },
    },
}


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
# HTTP API (sidecar paradiscovery por outros MCPs, ex: agent-twin)            #
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
def _build_http_app(store: ServiceStore) -> FastAPI:
    from fastapi.responses import StreamingResponse

    from ..tools.log_tool import _resolve_log_source, _stream_docker_logs, _stream_file_logs

    app = FastAPI(title="services-mcp API", version="0.1.0", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        try:
            count = len(store.list_all())
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "error": str(exc)}
        return {"status": "ok", "service": "services-mcp", "registered_services": count}

    @app.get("/v1/services/{name}/logs/stream")
    async def stream_logs(
        name: str,
        lines: int = 50,
        grep: str | None = None,
        timestamps: bool = False,
    ):
        """SSE endpoint — stream de logs em tempo real para um servico registrado."""
        svc = store.get(name)
        if svc is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Servico nao encontrado: {name}")

        source_info = _resolve_log_source(svc)
        source = source_info["source"]
        target = source_info["target"]

        if source == "docker":
            gen = _stream_docker_logs(target, lines=lines, grep=grep, timestamps=timestamps)
        elif source == "file":
            gen = _stream_file_logs(target, lines=lines, grep=grep)
        else:
            async def _no_source():
                yield 'data: {"error": "no_log_source", "detail": "Servico nao possui fonte de log configurada."}\n\n'
            gen = _no_source()

        return StreamingResponse(gen, media_type="text/event-stream")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "services-mcp", "docs": "/docs", "health": "/v1/health"}

    return app


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
# Server                                                                       #
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
def build_server() -> tuple[Any, ServiceStore, ServicesSettings, FastAPI]:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    store = ServiceStore(settings)
    http_app = _build_http_app(store)

    _log.info("services_mcp_ready")

    # Sincronizagateway no startup (non-blocking  -  ignoraerros)
    try:
        _log.info("sync_registry starting...")
        result = sync_registry(store, include_docker=True, probe_health=False)
        _log.info("sync_registry done: upserted=%d", result.get("total_upserted", 0))
    except Exception as exc:  # noqa: BLE001
        _log.warning("sync_registry startup failed (ignored): %s", exc)

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
    # â"€â"€ Registry â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
            runtime=args.get("runtime"),
            deploy_mode=args.get("deploy_mode"),
        )
    if name == "update_service":
        update_args = {k: v for k, v in args.items() if k != "name"}
        return update_service(store, name=args["name"], **update_args)
    if name == "unregister_service":
        return unregister_service(store, name=args["name"])
    # â"€â"€ PortMap â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
    if name == "get_port_map":
        return get_port_map(store)
    if name == "find_by_port":
        return find_by_port(store, port=args["port"])
    # â"€â"€ Discovery â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
    # â"€â"€ Composite â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
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
    # â"€â"€ Gateway â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
    if name == "get_gateway_map":
        return get_gateway_map(store)
    if name == "update_service_gateway":
        return update_service_gateway(
            store,
            name=args["name"],
            internal_url=args.get("internal_url"),
            external_url=args.get("external_url"),
            host=args.get("host"),
            port=args.get("port"),
            probe=args.get("probe", True),
        )
    if name == "sync_registry":
        return sync_registry(
            store,
            port_ranges=args.get("port_ranges"),
            service_names=args.get("service_names"),
            include_docker=args.get("include_docker", True),
            probe_health=args.get("probe_health", True),
            docker_timeout=args.get("docker_timeout", 10),
        )
    # â"€â"€ Launch â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
    if name == "launch_service":
        return launch_service(
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
        return stop_service(
            store,
            name=args["name"],
            mode=args.get("mode"),
            timeout=args.get("timeout", 10),
        )
    # â"€â"€ Env â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€ #
    if name == "read_env_file":
        return read_env_file(store, path=args["path"], key_filter=args.get("key_filter"))
    if name == "set_env_var":
        return set_env_var(
            store,
            path=args["path"],
            key=args["key"],
            value=args["value"],
            create_if_missing=args.get("create_if_missing", True),
            comment=args.get("comment"),
        )
    if name == "sync_service_urls":
        return sync_service_urls(
            store,
            path=args["path"],
            url_map=args.get("url_map"),
            url_suffix=args.get("url_suffix", ""),
            dry_run=args.get("dry_run", False),
        )
    if name == "audit_env_files":
        return audit_env_files(
            store,
            directory=args["directory"],
            include_pattern=args.get("include_pattern", ".env*"),
            check_registry_urls=args.get("check_registry_urls", True),
        )
    if name == "redact_env_secrets":
        return redact_env_secrets(
            store,
            paths=args["paths"],
            keys=args.get("keys"),
            auto_detect=args.get("auto_detect", True),
            dry_run=args.get("dry_run", False),
        )
    # -- Infra ------------------------------------------------------------------
    if name == "register_infra":
        return register_infra(
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
        return scan_infra(
            store,
            timeout=args.get("timeout", 10),
            environment=args.get("environment", "local"),
        )
    if name == "sync_infra_env":
        return sync_infra_env(
            store,
            path=args["path"],
            dry_run=args.get("dry_run", False),
            db_kind=args.get("db_kind"),
        )
    # -- Brokers ----------------------------------------------------------------
    if name == "kafka_status":
        return kafka_status(store, bootstrap_servers=args.get("bootstrap_servers"))
    if name == "redis_status":
        return redis_status(store, url=args.get("url"))
    if name == "sync_broker_urls":
        return sync_broker_urls(store, path=args["path"], dry_run=args.get("dry_run", False))
    # -- Logs -------------------------------------------------------------------
    if name == "get_service_logs":
        return get_service_logs(
            store,
            name=args["name"],
            lines=args.get("lines", 100),
            since=args.get("since"),
            grep=args.get("grep"),
            timestamps=args.get("timestamps", False),
        )
    if name == "search_logs":
        return search_logs(
            store,
            name=args["name"],
            pattern=args["pattern"],
            lines=args.get("lines", 500),
            since=args.get("since"),
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
