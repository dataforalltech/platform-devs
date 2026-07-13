"""Servidor MCP deploy — sidecar kind=mcp_http, GATEWAY-READY (Model C).

deploy-mcp é COMPUTE + STATEFUL: cada tool de ação FAZ a operação real (git, GitHub,
deploy, ACR, CI) via o `GitHubClient` e, DEPOIS do sucesso, **registra a operação num
ledger persistido** (dual-db, tenant-scoped, credencial-zero). Padrão: "faz a ação →
registra no ledger". 30 tools:

  Git (4):            list_repos, create_branch, list_branches, commit_files
  PR (4):             create_pr, get_pr, merge_pr, list_prs
  Workflow (4):       trigger_workflow, list_workflow_runs, get_workflow_run, cancel_workflow_run
  Deploy (2):         deploy, get_deploy_status
  Pipeline (2):       scaffold_pipeline, get_pipeline_templates
  ACR (3):            setup_repo, acr_build, list_acr_images
  Healthcheck (1):    ensure_all_repos_healthy
  Local Workspace (4): get_repos_root, set_repos_root, list_local_repos, clone_repo
  Ledger (6, novas — leem o histórico persistido): list_deployments, get_deployment,
     list_deploy_events, list_pr_history, list_workflow_history, list_registered_repos

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:deploy-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3); o ledger é escrito/lido no banco DESSE tenant.
  4. _EXCLUDE_TOOLS (denylist fail-safe). /docs desabilitado (DOCS_ENABLED=false).

Persistência: as tools de ação usam o `GitHubClient` (síncrono, inalterado) para a
ação; o `_run_tool` (async) abre uma sessão tenant-scoped (`for_tenant`, credencial-
zero, ORM-H-12) e persiste o ledger via `DeployStore`. Tools puramente compute/read
(templates, workspace, list_* live do GitHub) NÃO abrem pool — só rodam e retornam.

Transporte: stdio (primário, MCP — fail-closed, sem tenant) + sidecar HTTP (:MCP_PORT):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório; tenant dos claims)
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
from ..config.settings import NAMESPACE, DeploySettings, get_settings
from ..db.schema import ensure_schema
from ..db.store import DeployStore
from ..knowledge.github_client import GitHubClient
from ..tools import (
    acr_build,
    cancel_workflow_run,
    clone_repo,
    commit_files,
    create_branch,
    create_pr,
    deploy,
    ensure_all_repos_healthy,
    get_deploy_status,
    get_deployment,
    get_pipeline_templates,
    get_pr,
    get_repos_root,
    get_workflow_run,
    list_acr_images,
    list_branches,
    list_deploy_events,
    list_deployments,
    list_local_repos,
    list_pr_history,
    list_prs,
    list_registered_repos,
    list_repos,
    list_workflow_history,
    list_workflow_runs,
    merge_pr,
    scaffold_pipeline,
    set_repos_root,
    setup_repo,
    trigger_workflow,
)

_log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────── #
# Schemas                                                                      #
# ─────────────────────────────────────────────────────────────────────────── #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Git ───────────────────────────────────────────────────────────────── #
    "list_repos": {
        "description": (
            "Lista repositórios da organização GitHub. "
            "Útil para descobrir nomes exatos antes de operar em um repo."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "description": "Organização. Default: DEPLOY_GITHUB_ORG.",
                },
                "filter_name": {
                    "type": "string",
                    "description": "Filtro substring no nome (case-insensitive).",
                },
                "include_archived": {
                    "type": "boolean",
                    "description": "Incluir repos arquivados. Default: false.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
    },
    "create_branch": {
        "description": (
            "Cria uma branch em um repositório a partir de um ref (branch, tag ou SHA). "
            "Use antes de commit_files para ter uma branch de trabalho."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Nome do repo (owner/name ou só name)."},
                "branch": {"type": "string", "description": "Nome da nova branch."},
                "from_ref": {
                    "type": "string",
                    "description": "Branch/tag/SHA base. Default: develop.",
                    "default": "develop",
                },
            },
            "required": ["repo", "branch"],
            "additionalProperties": False,
        },
    },
    "list_branches": {
        "description": "Lista branches de um repositório com nome, SHA e status de proteção.",
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "filter_name": {
                    "type": "string",
                    "description": "Filtro substring (ex: 'feature/', 'release/').",
                },
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    "commit_files": {
        "description": (
            "Cria ou atualiza arquivos em um commit. "
            "Para 1 arquivo usa Contents API. "
            "Para N arquivos usa Git Data API (1 commit atômico). "
            "Cria o arquivo se não existir, atualiza se existir."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "branch": {"type": "string", "description": "Branch de destino."},
                "message": {"type": "string", "description": "Mensagem do commit."},
                "files": {
                    "type": "array",
                    "description": "Arquivos a criar/atualizar.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Caminho relativo ao root (ex: src/main.py).",
                            },
                            "content": {
                                "type": "string",
                                "description": "Conteúdo completo do arquivo.",
                            },
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
                "author_name": {
                    "type": "string",
                    "description": "Nome do autor (override). Default: usa o token.",
                },
                "author_email": {"type": "string"},
            },
            "required": ["repo", "branch", "message", "files"],
            "additionalProperties": False,
        },
    },
    # ── PR ────────────────────────────────────────────────────────────────── #
    "create_pr": {
        "description": (
            "Abre um Pull Request. Suporta labels, reviewers e modo draft. "
            "Retorna número do PR, URL e estado inicial."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string", "description": "Título do PR."},
                "body": {"type": "string", "description": "Descrição em markdown."},
                "head": {
                    "type": "string",
                    "description": "Branch de origem (feature/minha-feature).",
                },
                "base": {
                    "type": "string",
                    "description": "Branch de destino. Default: develop.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels a aplicar.",
                },
                "reviewers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Logins de reviewers.",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Criar como rascunho. Default: false.",
                    "default": False,
                },
            },
            "required": ["repo", "title", "head"],
            "additionalProperties": False,
        },
    },
    "get_pr": {
        "description": (
            "Retorna detalhes de um PR: estado, mergeable_state, check runs (CI status) "
            "e informações de review."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "pr_number": {"type": "integer", "description": "Número do PR."},
            },
            "required": ["repo", "pr_number"],
            "additionalProperties": False,
        },
    },
    "merge_pr": {
        "description": (
            "Faz merge de um PR. Estratégias: squash (padrão), merge, rebase. "
            "Verifique get_pr antes para garantir checks passando."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "pr_number": {"type": "integer"},
                "method": {
                    "type": "string",
                    "enum": ["squash", "merge", "rebase"],
                    "description": "Estratégia de merge. Default: squash.",
                    "default": "squash",
                },
                "commit_title": {
                    "type": "string",
                    "description": "Título do commit de merge (override).",
                },
                "commit_message": {
                    "type": "string",
                    "description": "Mensagem do commit de merge (override).",
                },
            },
            "required": ["repo", "pr_number"],
            "additionalProperties": False,
        },
    },
    "list_prs": {
        "description": "Lista Pull Requests de um repositório com filtros opcionais.",
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Estado dos PRs. Default: open.",
                    "default": "open",
                },
                "base": {
                    "type": "string",
                    "description": "Filtrar por branch de destino (ex: main, develop).",
                },
                "author": {
                    "type": "string",
                    "description": "Filtrar por login do autor.",
                },
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    # ── Workflow ──────────────────────────────────────────────────────────── #
    "trigger_workflow": {
        "description": (
            "Dispara um workflow via workflow_dispatch. "
            "workflow_id pode ser o nome do arquivo (deploy.yml) ou ID numérico. "
            "A API não retorna o run_id — use list_workflow_runs após para localizar o run."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "workflow_id": {
                    "type": "string",
                    "description": "Nome do arquivo do workflow (ex: deploy.yml) ou ID.",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch, tag ou SHA para o dispatch.",
                },
                "inputs": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Inputs do workflow_dispatch (chave → valor string).",
                },
            },
            "required": ["repo", "workflow_id", "ref"],
            "additionalProperties": False,
        },
    },
    "list_workflow_runs": {
        "description": (
            "Lista runs recentes de workflows. Use após trigger_workflow para encontrar o run_id do dispatch."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "workflow_id": {
                    "type": "string",
                    "description": "Filtrar por workflow (arquivo ou ID). Default: todos.",
                },
                "branch": {"type": "string", "description": "Filtrar por branch."},
                "status": {
                    "type": "string",
                    "enum": [
                        "queued",
                        "in_progress",
                        "completed",
                        "success",
                        "failure",
                        "cancelled",
                    ],
                    "description": "Filtrar por status.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Máximo de runs. Default: 10.",
                    "default": 10,
                },
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    "get_workflow_run": {
        "description": (
            "Retorna status detalhado de um workflow run: "
            "status (queued/in_progress/completed), conclusion (success/failure/cancelled), "
            "branch, SHA, URL e logs_url."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "run_id": {"type": "integer", "description": "ID numérico do run."},
            },
            "required": ["repo", "run_id"],
            "additionalProperties": False,
        },
    },
    "cancel_workflow_run": {
        "description": "Cancela um workflow run em andamento (queued ou in_progress).",
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "run_id": {"type": "integer"},
            },
            "required": ["repo", "run_id"],
            "additionalProperties": False,
        },
    },
    # ── Deploy ────────────────────────────────────────────────────────────── #
    "deploy": {
        "description": (
            "Dispara o deploy de um serviço para um ambiente. "
            "Mapeia automaticamente ambiente → workflow:\n"
            "  dev  → cd-dev.yml   @ develop\n"
            "  hml  → cd-hml.yml   @ release/<versao>  (ref obrigatório)\n"
            "  prod → cd-prod.yml  @ v<semver>           (ref obrigatório)\n"
            "Para prod é necessário aprovação manual configurada no GitHub Environment."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Nome do serviço (usado como nome do repo se repo não informado).",
                },
                "environment": {
                    "type": "string",
                    "enum": ["dev", "hml", "prod"],
                    "description": "Ambiente alvo.",
                },
                "ref": {
                    "type": "string",
                    "description": (
                        "Branch/tag para o dispatch. "
                        "Obrigatório para hml (release/1.0.0) e prod (v1.0.0). "
                        "Para dev o default é develop."
                    ),
                },
                "repo": {
                    "type": "string",
                    "description": "Nome do repo (se diferente do service).",
                },
                "inputs": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Inputs extras para o workflow_dispatch.",
                },
            },
            "required": ["service", "environment"],
            "additionalProperties": False,
        },
    },
    "get_deploy_status": {
        "description": (
            "Retorna os últimos runs de deploy para um serviço e ambiente. "
            "Mostra status (in_progress/completed), conclusion (success/failure) "
            "e URL de cada run."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "environment": {
                    "type": "string",
                    "enum": ["dev", "hml", "prod"],
                },
                "repo": {
                    "type": "string",
                    "description": "Nome do repo (se diferente do service).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Máximo de runs. Default: 5.",
                    "default": 5,
                },
            },
            "required": ["service", "environment"],
            "additionalProperties": False,
        },
    },
    # ── Pipeline ──────────────────────────────────────────────────────────── #
    "scaffold_pipeline": {
        "description": (
            "Instala os workflows padrão do platform-service-template em um repositório. "
            "Cria/atualiza .github/workflows/*.yml via commit. "
            "Os templates são genéricos — IMAGE_NAME e secrets são configurados no repo via "
            "Settings → Secrets and variables. "
            "Use get_pipeline_templates para ver os templates disponíveis."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Nome do repo alvo."},
                "templates": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["ci", "deploy", "cd-dev", "cd-hml", "cd-prod", "pr-validate"],
                    },
                    "description": (
                        "Templates a instalar. "
                        "Default: todos (ci, deploy, cd-dev, cd-hml, cd-prod, pr-validate)."
                    ),
                },
                "branch": {
                    "type": "string",
                    "description": "Branch onde fazer o commit. Default: develop.",
                    "default": "develop",
                },
                "commit_message": {
                    "type": "string",
                    "description": "Mensagem do commit. Default: mensagem padrão.",
                },
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    "get_pipeline_templates": {
        "description": (
            "Lista os templates de CI/CD disponíveis para scaffold_pipeline. "
            "Inclui nome, descrição, secrets/variables obrigatórios e trigger de cada template."
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    # ── ACR ───────────────────────────────────────────────────────────────── #
    "setup_repo": {
        "description": (
            "Configura um repositório para deploy automático no ACR. "
            "Propaga as credenciais ACR do deploy-mcp como GitHub Actions secrets no repo alvo "
            "— elimina configuração manual por repo.\n\n"
            "Secrets definidos: ACR_USERNAME, ACR_PASSWORD (+ PORTAINER_WEBHOOK_URL e "
            "TOKEN_GITHUB se informados).\n"
            "Variável definida: IMAGE_NAME.\n\n"
            "Após setup_repo, dispare trigger_workflow(workflow_id='deploy.yml') para buildar "
            "e enviar a imagem."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Nome do repo (owner/name ou só name — usa DEPLOY_GITHUB_ORG).",
                },
                "image_name": {
                    "type": "string",
                    "description": "Nome da imagem Docker no ACR (ex: platform-analytics).",
                },
                "portainer_webhook": {
                    "type": "string",
                    "description": "URL do webhook do Portainer para este repo (opcional).",
                },
                "github_token": {
                    "type": "string",
                    "description": "PAT para builds com dependências privadas (opcional).",
                },
            },
            "required": ["repo", "image_name"],
            "additionalProperties": False,
        },
    },
    "acr_build": {
        "description": (
            "Constrói e empurra uma imagem Docker para o ACR localmente via docker CLI. "
            "Não depende de GitHub Actions — útil para deploy imediato.\n\n"
            "Fluxo: docker login → docker build (:vX + :latest) → docker push.\n"
            "Tag padrão: v3.{YYYYMMDD}-{sha7}.\n"
            "Imagem: {ACR_REGISTRY}/{ACR_NAMESPACE}/{image_name}."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório com o Dockerfile.",
                },
                "image_name": {
                    "type": "string",
                    "description": "Nome da imagem (ex: platform-analytics).",
                },
                "tag": {
                    "type": "string",
                    "description": "Tag da imagem. Default: v3.{YYYYMMDD}-{sha7}.",
                },
                "dockerfile": {
                    "type": "string",
                    "description": "Caminho do Dockerfile relativo a repo_path. Default: Dockerfile.",
                    "default": "Dockerfile",
                },
                "push": {
                    "type": "boolean",
                    "description": "Empurrar para o ACR após o build. Default: true.",
                    "default": True,
                },
            },
            "required": ["repo_path", "image_name"],
            "additionalProperties": False,
        },
    },
    # ── Healthcheck ───────────────────────────────────────────────────────────── #
    "ensure_all_repos_healthy": {
        "description": (
            "Verifica e garante que todos os repositórios elegíveis para automação "
            "(active=true AND allows_automation=true — ADR-002) tenham CI passando "
            "e imagem Docker publicada no ACR.\n\n"
            "Para cada repo classifica: HEALTHY | CI_FAILING | ACR_MISSING | CI_FAILING_AND_ACR_MISSING.\n\n"
            "Remediação automática (dry_run=false):\n"
            "  • CI falhando/ausente → scaffold ci+cd-dev se necessário → trigger ci.yml → polling\n"
            "  • ACR ausente → setup_repo (injeta secrets ACR) → trigger cd-dev.yml\n\n"
            "Use dry_run=true para apenas inspecionar sem modificar nada."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "description": "Organização GitHub. Default: dataforalltech.",
                    "default": "dataforalltech",
                },
                "workflow_id": {
                    "type": "string",
                    "description": "Arquivo do workflow CI a verificar/disparar. Default: ci.yml.",
                    "default": "ci.yml",
                },
                "cd_workflow_id": {
                    "type": "string",
                    "description": "Arquivo do workflow CD para build ACR. Default: cd-dev.yml.",
                    "default": "cd-dev.yml",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch para verificar e disparar workflows. Default: develop.",
                    "default": "develop",
                },
                "wait_minutes": {
                    "type": "integer",
                    "description": "Tempo máximo aguardando CI após remediação (minutos). Default: 10.",
                    "minimum": 1,
                    "maximum": 60,
                    "default": 10,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Se true, apenas inspeciona e reporta sem executar nenhuma ação. Default: false.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
    },
    "list_acr_images": {
        "description": (
            "Lista as tags disponíveis de uma imagem no ACR, ordenadas por data (mais recente primeiro). "
            "Útil para verificar quais versões estão publicadas antes de um rollback ou deploy."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Nome do serviço/imagem (ex: platform-analytics).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Máximo de tags a retornar. Default: 20.",
                    "default": 20,
                },
            },
            "required": ["service_name"],
            "additionalProperties": False,
        },
    },
    # ── Local Workspace ──────────────────────────────────────────────────── #
    "get_repos_root": {
        "description": (
            "Retorna o caminho resolvido de REPOS_ROOT e quantos repos existem la. "
            "Resolucao: argumento > DEPLOY_REPOS_ROOT > REPOS_ROOT > config-mcp workspace > auto-detect. "
            "Use para descobrir onde os repos estao antes de clonar ou listar."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "explicit": {
                    "type": "string",
                    "description": "Caminho explicito a usar (sobrepoe todas as outras fontes).",
                },
            },
        },
    },
    "set_repos_root": {
        "description": (
            "Define a pasta raiz dos repositorios locais. "
            "Persiste REPOS_ROOT no config-mcp (namespace workspace) para uso em todas as sessoes. "
            "create_dir=true cria o diretorio se nao existir. "
            "persist=false (default true) apenas valida sem salvar no config-mcp."
        ),
        "schema": {
            "type": "object",
            "required": ["path"],
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho absoluto (ou ~ expandido) da pasta de repos.",
                },
                "create_dir": {
                    "type": "boolean",
                    "default": False,
                    "description": "Cria o diretorio se nao existir. Default: false.",
                },
                "persist": {
                    "type": "boolean",
                    "default": True,
                    "description": "Salva no config-mcp para persistir entre sessoes. Default: true.",
                },
            },
        },
    },
    "list_local_repos": {
        "description": (
            "Lista repositorios clonados em REPOS_ROOT. "
            "Para cada repo com .git retorna: branch atual, remote origin, ultimo commit, dirty flag, latest tag. "
            "filter_name: filtra por substring no nome. "
            "include_git_info=false retorna apenas nomes (muito mais rapido para muitos repos)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repos_root": {
                    "type": "string",
                    "description": "Caminho da pasta de repos (sobrepoe REPOS_ROOT configurado).",
                },
                "filter_name": {
                    "type": "string",
                    "description": "Filtro substring case-insensitive no nome do repo.",
                },
                "include_git_info": {
                    "type": "boolean",
                    "default": True,
                    "description": "Coleta branch, remote, commits de cada repo. Default: true.",
                },
            },
        },
    },
    "clone_repo": {
        "description": (
            "Clona um repositorio do GitHub para REPOS_ROOT/<repo>. "
            "repo: nome simples ('platform-auth') ou 'owner/repo'. "
            "Usa o GITHUB_TOKEN configurado (sem expor o token no remote URL retornado). "
            "depth: shallow clone para repos grandes."
        ),
        "schema": {
            "type": "object",
            "required": ["repo"],
            "additionalProperties": False,
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Nome do repo ('platform-auth') ou 'owner/repo'.",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch/tag/SHA a clonar. Default: branch padrao do repo.",
                },
                "repos_root": {
                    "type": "string",
                    "description": "Pasta destino (sobrepoe REPOS_ROOT configurado).",
                },
                "target_dir": {
                    "type": "string",
                    "description": "Nome do diretorio destino. Default: nome do repo.",
                },
                "depth": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Shallow clone --depth N. Default: clone completo.",
                },
            },
        },
    },
    # ── Ledger (consulta do histórico persistido — dual-db, tenant-scoped) ──── #
    "list_deployments": {
        "description": (
            "Lista o histórico de deploys persistido no ledger do tenant, com filtros "
            "opcionais por service/environment/status. Lê do banco (não do GitHub)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "service": {"type": "string", "description": "Filtrar por serviço."},
                "environment": {
                    "type": "string",
                    "enum": ["dev", "hml", "prod"],
                    "description": "Filtrar por ambiente.",
                },
                "status": {"type": "string", "description": "Filtrar por status."},
            },
        },
    },
    "get_deployment": {
        "description": "Retorna um registro de deploy do ledger por id.",
        "schema": {
            "type": "object",
            "required": ["id"],
            "additionalProperties": False,
            "properties": {"id": {"type": "integer", "description": "Id do deploy no ledger."}},
        },
    },
    "list_deploy_events": {
        "description": (
            "Lista os eventos genéricos do ledger (clone/commit/acr_build/cancel_run/"
            "scaffold_pipeline/trigger_workflow), com filtros opcionais por kind/target."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string", "description": "Filtrar por tipo de evento."},
                "target": {"type": "string", "description": "Filtrar por alvo (repo/imagem/run)."},
            },
        },
    },
    "list_pr_history": {
        "description": (
            "Lista o histórico de Pull Requests persistido no ledger (upsert por "
            "repo+number), com filtros opcionais por repo/state. Lê do banco."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo": {"type": "string", "description": "Filtrar por repositório."},
                "state": {"type": "string", "description": "Filtrar por estado (open/closed/merged)."},
            },
        },
    },
    "list_workflow_history": {
        "description": (
            "Lista o histórico de workflow runs persistido no ledger (upsert por "
            "repo+run_id), com filtros opcionais por repo/status. Lê do banco."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo": {"type": "string", "description": "Filtrar por repositório."},
                "status": {"type": "string", "description": "Filtrar por status do run."},
            },
        },
    },
    "list_registered_repos": {
        "description": (
            "Lista os repositórios registrados no ledger (via setup_repo) com sua "
            "config e status. Lê do banco do tenant."
        ),
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
}


# ── Policy metadata (STD-MCP-001 CI-2) ────────────────────────────────────────
# Cada tool declara os 4 campos de política, injetados em _TOOL_SCHEMAS abaixo:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução dominio:tipo:acao (least-privilege, 3 seg.)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação)
# Verbo :read = consulta/status (não muta estado remoto); :write = MUTA (git, PR,
# deploy, push ACR, workflow, clone, persiste config) — SENSÍVEIS.
_POLICY: dict[str, dict[str, str]] = {
    # ── Git ──────────────────────────────────────────────────────────────────
    "list_repos": {
        "required_scope": f"{NAMESPACE}:repo:read",
        "resource_type": "repo",
        "data_domain": "source_control",
    },
    "create_branch": {
        "required_scope": f"{NAMESPACE}:branch:write",
        "resource_type": "branch",
        "data_domain": "source_control",
    },
    "list_branches": {
        "required_scope": f"{NAMESPACE}:branch:read",
        "resource_type": "branch",
        "data_domain": "source_control",
    },
    "commit_files": {
        "required_scope": f"{NAMESPACE}:commit:write",
        "resource_type": "commit",
        "data_domain": "source_control",
    },
    # ── PR ───────────────────────────────────────────────────────────────────
    "create_pr": {
        "required_scope": f"{NAMESPACE}:pr:write",
        "resource_type": "pull_request",
        "data_domain": "source_control",
    },
    "get_pr": {
        "required_scope": f"{NAMESPACE}:pr:read",
        "resource_type": "pull_request",
        "data_domain": "source_control",
    },
    "merge_pr": {
        "required_scope": f"{NAMESPACE}:pr:write",
        "resource_type": "pull_request",
        "data_domain": "source_control",
    },
    "list_prs": {
        "required_scope": f"{NAMESPACE}:pr:read",
        "resource_type": "pull_request",
        "data_domain": "source_control",
    },
    # ── Workflow ─────────────────────────────────────────────────────────────
    "trigger_workflow": {
        "required_scope": f"{NAMESPACE}:workflow:write",
        "resource_type": "workflow",
        "data_domain": "cicd",
    },
    "list_workflow_runs": {
        "required_scope": f"{NAMESPACE}:workflow:read",
        "resource_type": "workflow",
        "data_domain": "cicd",
    },
    "get_workflow_run": {
        "required_scope": f"{NAMESPACE}:workflow:read",
        "resource_type": "workflow",
        "data_domain": "cicd",
    },
    "cancel_workflow_run": {
        "required_scope": f"{NAMESPACE}:workflow:write",
        "resource_type": "workflow",
        "data_domain": "cicd",
    },
    # ── Deploy ───────────────────────────────────────────────────────────────
    "deploy": {
        "required_scope": f"{NAMESPACE}:deployment:write",
        "resource_type": "deployment",
        "data_domain": "cicd",
    },
    "get_deploy_status": {
        "required_scope": f"{NAMESPACE}:deployment:read",
        "resource_type": "deployment",
        "data_domain": "cicd",
    },
    # ── Pipeline ─────────────────────────────────────────────────────────────
    "scaffold_pipeline": {
        "required_scope": f"{NAMESPACE}:pipeline:write",
        "resource_type": "pipeline",
        "data_domain": "cicd",
    },
    "get_pipeline_templates": {
        "required_scope": f"{NAMESPACE}:pipeline:read",
        "resource_type": "pipeline",
        "data_domain": "cicd",
    },
    # ── ACR ──────────────────────────────────────────────────────────────────
    "setup_repo": {
        "required_scope": f"{NAMESPACE}:repo:write",
        "resource_type": "repo",
        "data_domain": "cicd",
    },
    "acr_build": {
        "required_scope": f"{NAMESPACE}:image:write",
        "resource_type": "image",
        "data_domain": "artifact",
    },
    "list_acr_images": {
        "required_scope": f"{NAMESPACE}:image:read",
        "resource_type": "image",
        "data_domain": "artifact",
    },
    # ── Healthcheck ──────────────────────────────────────────────────────────
    "ensure_all_repos_healthy": {
        "required_scope": f"{NAMESPACE}:deployment:write",
        "resource_type": "deployment",
        "data_domain": "cicd",
    },
    # ── Local workspace ──────────────────────────────────────────────────────
    "get_repos_root": {
        "required_scope": f"{NAMESPACE}:workspace:read",
        "resource_type": "workspace",
        "data_domain": "workspace",
    },
    "set_repos_root": {
        "required_scope": f"{NAMESPACE}:workspace:write",
        "resource_type": "workspace",
        "data_domain": "workspace",
    },
    "list_local_repos": {
        "required_scope": f"{NAMESPACE}:workspace:read",
        "resource_type": "workspace",
        "data_domain": "workspace",
    },
    "clone_repo": {
        "required_scope": f"{NAMESPACE}:workspace:write",
        "resource_type": "workspace",
        "data_domain": "workspace",
    },
    # ── Ledger (consulta do histórico persistido — :read, tenant-scoped) ──────
    "list_deployments": {
        "required_scope": f"{NAMESPACE}:deployment:read",
        "resource_type": "deployment",
        "data_domain": "cicd",
    },
    "get_deployment": {
        "required_scope": f"{NAMESPACE}:deployment:read",
        "resource_type": "deployment",
        "data_domain": "cicd",
    },
    "list_deploy_events": {
        "required_scope": f"{NAMESPACE}:event:read",
        "resource_type": "event",
        "data_domain": "cicd",
    },
    "list_pr_history": {
        "required_scope": f"{NAMESPACE}:pr:read",
        "resource_type": "pull_request",
        "data_domain": "source_control",
    },
    "list_workflow_history": {
        "required_scope": f"{NAMESPACE}:workflow:read",
        "resource_type": "workflow",
        "data_domain": "cicd",
    },
    "list_registered_repos": {
        "required_scope": f"{NAMESPACE}:repo:read",
        "resource_type": "repo",
        "data_domain": "cicd",
    },
}

assert set(_POLICY.keys()) == set(_TOOL_SCHEMAS.keys()), "_POLICY cobre todas as tools"  # noqa: S101

# Injeta capability + os 3 campos de policy em cada entrada de _TOOL_SCHEMAS,
# para que /mcp/tools/list os emita (o gateway lê estes campos, CI-2).
for _name, _meta in _TOOL_SCHEMAS.items():
    _meta["capability"] = f"{NAMESPACE}.{_name}"
    _meta.update(_POLICY[_name])

# deploy-mcp é tenant-scoped e gateway-only: TODA tool exige inner token válido (com
# tenant nos claims). Não há tool tokenless — o liveness é o endpoint /v1/health.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredo NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Tools NOVAS que LEEM o ledger persistido (abrem sessão tenant-scoped p/ ler do DB).
# São roteadas para `_dispatch_ledger` (async), não para o `_dispatch` compute/GitHub.
_LEDGER_QUERY_TOOLS: frozenset[str] = frozenset(
    {
        "list_deployments",
        "get_deployment",
        "list_deploy_events",
        "list_pr_history",
        "list_workflow_history",
        "list_registered_repos",
    }
)

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: DeploySettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:deploy-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:deploy-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Ledger: mapa ação → persistência (após a ação ter SUCESSO) ────────────────
# Cada persister recebe (store, args, result) e grava a row/evento certo. O ledger é
# best-effort: a ação já teve sucesso no GitHub/ACR/git; uma falha ao gravar o ledger
# é logada mas NUNCA desfaz nem esconde a ação (as ações existentes não podem quebrar).


def _is_ok(payload: Any) -> bool:
    """True se o payload da ação não carrega um `error` (só então persistimos o ledger)."""
    return isinstance(payload, dict) and "error" not in payload


async def _persist_deploy(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    await store.record_deployment(
        service=result.get("service") or args.get("service") or "",
        environment=result.get("environment") or args.get("environment") or "",
        status="dispatched" if result.get("dispatched") else "unknown",
        ref=result.get("ref"),
        repo=result.get("repo"),
        workflow=result.get("workflow"),
        detail=result,
    )


async def _persist_create_pr(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    number = result.get("number")
    if number is None:
        return
    await store.upsert_pull_request(
        repo=args.get("repo") or "",
        number=int(number),
        title=result.get("title"),
        base=result.get("base"),
        head=result.get("head"),
        url=result.get("url"),
        state=result.get("state"),
    )


async def _persist_get_pr(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    number = result.get("number") or args.get("pr_number")
    if number is None:
        return
    await store.upsert_pull_request(
        repo=args.get("repo") or "",
        number=int(number),
        title=result.get("title"),
        base=result.get("base"),
        head=result.get("head"),
        url=result.get("url"),
        state=result.get("state"),
    )


async def _persist_merge_pr(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    number = args.get("pr_number")
    if number is None:
        return
    # Só state='merged' — _prune preserva título/base/head do create_pr/get_pr anterior.
    await store.upsert_pull_request(repo=args.get("repo") or "", number=int(number), state="merged")


async def _persist_create_branch(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    await store.upsert_branch(
        repo=result.get("repo") or args.get("repo") or "",
        branch=result.get("branch") or args.get("branch") or "",
        from_ref=args.get("from_ref", "develop"),
        status="created",
    )


async def _persist_trigger_workflow(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    # O dispatch do GitHub NÃO retorna run_id (a chave natural (repo, run_id) do
    # WorkflowRunRow exige um); então o disparo entra como evento append-only. O run
    # real, com id, é gravado por get_workflow_run (upsert refresh). Ver relatório.
    await store.record_event(
        kind="trigger_workflow",
        target=f"{args.get('repo')}/{args.get('workflow_id')}",
        status="dispatched" if result.get("dispatched") else "unknown",
        detail=result,
    )


async def _persist_get_workflow_run(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    run_id = result.get("id") or args.get("run_id")
    if run_id is None:
        return
    await store.upsert_workflow_run(
        repo=args.get("repo") or "",
        run_id=str(run_id),
        workflow=result.get("name"),
        status=result.get("status"),
        conclusion=result.get("conclusion"),
        detail=result,
    )


async def _persist_cancel_workflow_run(
    store: DeployStore, args: dict[str, Any], result: dict[str, Any]
) -> None:
    await store.record_event(
        kind="cancel_run",
        target=f"{args.get('repo')}#{args.get('run_id')}",
        status="cancelled" if result.get("cancelled") else "cancel_requested",
        detail=result,
    )


async def _persist_commit_files(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    await store.record_event(
        kind="commit",
        target=f"{args.get('repo')}@{args.get('branch')}",
        status="committed",
        detail={"sha": result.get("sha"), "url": result.get("url"), "files": result.get("files")},
    )


async def _persist_acr_build(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    await store.record_event(
        kind="acr_build",
        target=result.get("image") or args.get("image_name"),
        status="success" if result.get("success") else "built",
        detail=result,
    )


async def _persist_scaffold_pipeline(
    store: DeployStore, args: dict[str, Any], result: dict[str, Any]
) -> None:
    await store.record_event(
        kind="scaffold_pipeline",
        target=result.get("repo") or args.get("repo"),
        status="committed" if result.get("committed") else "done",
        detail={
            "sha": result.get("sha"),
            "branch": result.get("branch"),
            "files_installed": result.get("files_installed"),
        },
    )


async def _persist_clone_repo(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    await store.record_event(
        kind="clone",
        target=result.get("repo") or args.get("repo"),
        status=result.get("action") or "cloned",
        detail={
            "path": result.get("path"),
            "branch": result.get("branch"),
            "last_commit": result.get("last_commit"),
        },
    )


async def _persist_setup_repo(store: DeployStore, args: dict[str, Any], result: dict[str, Any]) -> None:
    await store.upsert_repo(
        repo=result.get("repo") or args.get("repo") or "",
        config={
            "image_name": result.get("image_name"),
            "registry": result.get("registry"),
            "configured": result.get("configured"),
        },
        status="configured" if result.get("success") else "partial",
    )


# Só as tools de AÇÃO persistem. As compute/read (templates, workspace, list_* live do
# GitHub) NÃO estão aqui — rodam e retornam sem abrir pool.
_LEDGER_PERSISTERS: dict[str, Any] = {
    "deploy": _persist_deploy,
    "create_pr": _persist_create_pr,
    "get_pr": _persist_get_pr,
    "merge_pr": _persist_merge_pr,
    "create_branch": _persist_create_branch,
    "trigger_workflow": _persist_trigger_workflow,
    "get_workflow_run": _persist_get_workflow_run,
    "cancel_workflow_run": _persist_cancel_workflow_run,
    "commit_files": _persist_commit_files,
    "acr_build": _persist_acr_build,
    "scaffold_pipeline": _persist_scaffold_pipeline,
    "clone_repo": _persist_clone_repo,
    "setup_repo": _persist_setup_repo,
}


# ── Dispatcher do ledger (async: recebe o store ligado ao pool do tenant) ──────


async def _dispatch_ledger(name: str, args: dict[str, Any], store: DeployStore) -> dict[str, Any]:
    """Despacha as tools NOVAS de consulta do ledger (leem do banco do tenant)."""
    if name == "list_deployments":
        return await list_deployments(
            store,
            service=args.get("service"),
            environment=args.get("environment"),
            status=args.get("status"),
        )
    if name == "get_deployment":
        return await get_deployment(store, deployment_id=args["id"])
    if name == "list_deploy_events":
        return await list_deploy_events(store, kind=args.get("kind"), target=args.get("target"))
    if name == "list_pr_history":
        return await list_pr_history(store, repo=args.get("repo"), state=args.get("state"))
    if name == "list_workflow_history":
        return await list_workflow_history(store, repo=args.get("repo"), status=args.get("status"))
    if name == "list_registered_repos":
        return await list_registered_repos(store)
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: DeploySettings, tenant_id: str) -> None:
    """Garante as tabelas do ledger no banco do tenant (uma vez por processo). O engine
    é o do dialeto do pool resolvido — é o ponto que faz o mesmo código servir o dual-db."""
    if tenant_id in _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if tenant_id in _SCHEMA_READY:
            return
        pool = await get_pool_for_tenant(settings, tenant_id, strict=True)
        await ensure_schema(pool, engine=dialect_for_pool(pool).name)
        _SCHEMA_READY.add(tenant_id)


async def _run_tool(
    name: str,
    arguments: dict[str, Any],
    settings: DeploySettings,
    client: GitHubClient,
    tenant_id: str,
) -> dict[str, Any]:
    """Executa a tool e, para as tools de ação, persiste o ledger no banco do tenant.

    - Tools de CONSULTA do ledger → abrem sessão tenant-scoped e leem do DB.
    - Tools de AÇÃO → rodam a ação (GitHubClient, síncrona, inalterada) e DEPOIS
      persistem o ledger (best-effort; a ação nunca é desfeita por falha de ledger).
    - Tools compute/read → só rodam e retornam (não abrem pool).
    """
    # Consultas do ledger: leem do banco (não tocam o GitHub).
    if name in _LEDGER_QUERY_TOOLS:
        await _ensure_tenant_schema(settings, tenant_id)
        async with for_tenant(tenant_id) as session:
            return await _dispatch_ledger(name, arguments, DeployStore(session))

    # Ação/compute existente (síncrona, inalterada). KeyError p/ tool desconhecida.
    payload = _dispatch(name, arguments, settings, client)

    # Persiste o ledger APÓS a ação ter sucesso (só as tools de ação têm persister).
    persister = _LEDGER_PERSISTERS.get(name)
    if persister is not None and _is_ok(payload):
        try:
            await _ensure_tenant_schema(settings, tenant_id)
            async with for_tenant(tenant_id) as session:
                await persister(DeployStore(session), arguments, payload)
        except Exception:  # noqa: BLE001 — ledger best-effort: a ação já teve sucesso
            _log.exception("ledger_persist_failed tool=%s tenant=%s", name, tenant_id)
    return payload


# ── HTTP Sidecar (health + bridge governado /mcp/tools/*) ─────────────────────


def _build_http_app(settings: DeploySettings, client: GitHubClient | None = None) -> FastAPI:
    """Cria o sidecar HTTP. O GitHubClient (backend do serviço) é construído a
    partir das settings quando não injetado (testes passam um mock)."""
    if client is None:
        client = GitHubClient(settings)

    app = FastAPI(
        title="deploy-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "deploy-mcp", "tools": len(_TOOL_SCHEMAS)}

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

        # Toda tool exige inner token válido; o tenant vem SEMPRE dos claims (SEC-035 /
        # INV-3), nunca de argumento do cliente. O ledger é escrito/lido nesse tenant.
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

        try:
            payload = await _run_tool(name, arguments, settings, client, str(tenant_id))
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
def build_server() -> tuple[Any, DeploySettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o GitHubClient e o sidecar HTTP.

    O ledger é tenant-scoped e resolvido por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast no boot (STD-SEC-001/004/006)
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant

    client = GitHubClient(settings)
    http_app = _build_http_app(settings, client)
    _log.info(
        "deploy_mcp_ready tools=%d github_org=%s acr_registry=%s engine=%s",
        len(_TOOL_SCHEMAS),
        settings.github_org,
        settings.acr_registry,
        settings.DB_ENGINE,
    )

    server: Server = Server("deploy-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). deploy-mcp é
        # tenant-scoped e gateway-only: a execução real entra pelo sidecar HTTP
        # (/mcp/tools/call), onde o tenant vem dos claims verificados. Aqui recusamos
        # fail-closed (sem tenant não há como escrever/ler o ledger).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "deploy-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
                    "(/mcp/tools/call) com o inner Twin Token — o tenant vem dos claims."
                ),
            }
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, http_app


def _arg(args: dict[str, Any], key: str, default: Any = None) -> Any:
    """Extrai um argumento cru do payload MCP.

    Retorna ``Any`` (preservando o default ``None`` quando ausente) para as
    ferramentas cujos parametros sao obrigatorios no inputSchema — o valor cru
    vem do cliente MCP e a validacao acontece na camada de tools/backend. Isso
    mantem a semantica atual (mesmo default) sem estreitar o tipo para o mypy.
    """
    return args.get(key, default)


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: DeploySettings,
    client: GitHubClient,
) -> dict:
    # ── Git ───────────────────────────────────────────────────────────────── #
    if name == "list_repos":
        return list_repos(
            client,
            org=args.get("org"),
            filter_name=args.get("filter_name"),
            include_archived=args.get("include_archived", False),
        )
    if name == "create_branch":
        return create_branch(
            client,
            repo=_arg(args, "repo"),
            branch=_arg(args, "branch"),
            from_ref=args.get("from_ref", "develop"),
        )
    if name == "list_branches":
        return list_branches(
            client,
            repo=_arg(args, "repo"),
            filter_name=args.get("filter_name"),
        )
    if name == "commit_files":
        return commit_files(
            client,
            repo=_arg(args, "repo"),
            branch=_arg(args, "branch"),
            message=_arg(args, "message"),
            files=args.get("files", []),
            author_name=args.get("author_name"),
            author_email=args.get("author_email"),
        )
    # ── PR ────────────────────────────────────────────────────────────────── #
    if name == "create_pr":
        return create_pr(
            client,
            repo=_arg(args, "repo"),
            title=_arg(args, "title"),
            body=args.get("body", ""),
            head=_arg(args, "head"),
            base=args.get("base"),
            labels=args.get("labels"),
            reviewers=args.get("reviewers"),
            draft=args.get("draft", False),
        )
    if name == "get_pr":
        return get_pr(client, repo=_arg(args, "repo"), pr_number=_arg(args, "pr_number"))
    if name == "merge_pr":
        return merge_pr(
            client,
            repo=_arg(args, "repo"),
            pr_number=_arg(args, "pr_number"),
            method=args.get("method", "squash"),
            commit_title=args.get("commit_title"),
            commit_message=args.get("commit_message"),
        )
    if name == "list_prs":
        return list_prs(
            client,
            repo=_arg(args, "repo"),
            state=args.get("state", "open"),
            base=args.get("base"),
            author=args.get("author"),
        )
    # ── Workflow ──────────────────────────────────────────────────────────── #
    if name == "trigger_workflow":
        return trigger_workflow(
            client,
            repo=_arg(args, "repo"),
            workflow_id=_arg(args, "workflow_id"),
            ref=_arg(args, "ref"),
            inputs=args.get("inputs"),
        )
    if name == "list_workflow_runs":
        return list_workflow_runs(
            client,
            repo=_arg(args, "repo"),
            workflow_id=_arg(args, "workflow_id"),
            branch=_arg(args, "branch"),
            status=args.get("status"),
            limit=args.get("limit", 10),
        )
    if name == "get_workflow_run":
        return get_workflow_run(client, repo=_arg(args, "repo"), run_id=_arg(args, "run_id"))
    if name == "cancel_workflow_run":
        return cancel_workflow_run(client, repo=_arg(args, "repo"), run_id=_arg(args, "run_id"))
    # ── Deploy ────────────────────────────────────────────────────────────── #
    if name == "deploy":
        return deploy(
            client,
            service=_arg(args, "service"),
            environment=_arg(args, "environment"),
            ref=_arg(args, "ref"),
            repo=_arg(args, "repo"),
            inputs=args.get("inputs"),
        )
    if name == "get_deploy_status":
        return get_deploy_status(
            client,
            service=_arg(args, "service"),
            environment=_arg(args, "environment"),
            repo=_arg(args, "repo"),
            limit=args.get("limit", 5),
        )
    # ── Pipeline ──────────────────────────────────────────────────────────── #
    if name == "scaffold_pipeline":
        return scaffold_pipeline(
            client,
            repo=_arg(args, "repo"),
            templates=args.get("templates"),
            branch=args.get("branch", "develop"),
            commit_message=args.get("commit_message"),
        )
    if name == "get_pipeline_templates":
        return get_pipeline_templates()
    # ── ACR ───────────────────────────────────────────────────────────────── #
    if name == "setup_repo":
        return setup_repo(
            client,
            settings,
            repo=_arg(args, "repo"),
            image_name=_arg(args, "image_name"),
            portainer_webhook=args.get("portainer_webhook"),
            github_token=args.get("github_token"),
        )
    if name == "acr_build":
        return acr_build(
            settings,
            repo_path=_arg(args, "repo_path"),
            image_name=_arg(args, "image_name"),
            tag=args.get("tag"),
            dockerfile=args.get("dockerfile", "Dockerfile"),
            push=args.get("push", True),
        )
    if name == "list_acr_images":
        return list_acr_images(
            client,
            settings,
            service_name=_arg(args, "service_name"),
            limit=args.get("limit", 20),
        )
    # ── Healthcheck ───────────────────────────────────────────────────────────── #
    if name == "ensure_all_repos_healthy":
        return ensure_all_repos_healthy(
            client,
            settings,
            org=args.get("org", "dataforalltech"),
            workflow_id=args.get("workflow_id", "ci.yml"),
            cd_workflow_id=args.get("cd_workflow_id", "cd-dev.yml"),
            ref=args.get("ref", "develop"),
            wait_minutes=args.get("wait_minutes", 10),
            dry_run=args.get("dry_run", False),
        )
    # ── Local Workspace ──────────────────────────────────────────────────────── #
    if name == "get_repos_root":
        return get_repos_root(settings, explicit=args.get("explicit"))
    if name == "set_repos_root":
        return set_repos_root(
            settings,
            path=args["path"],
            create_dir=args.get("create_dir", False),
            persist=args.get("persist", True),
        )
    if name == "list_local_repos":
        return list_local_repos(
            settings,
            repos_root=args.get("repos_root"),
            filter_name=args.get("filter_name"),
            include_git_info=args.get("include_git_info", True),
        )
    if name == "clone_repo":
        return clone_repo(
            client,
            settings,
            repo=args["repo"],
            branch=_arg(args, "branch"),
            repos_root=args.get("repos_root"),
            target_dir=args.get("target_dir"),
            depth=args.get("depth"),
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
