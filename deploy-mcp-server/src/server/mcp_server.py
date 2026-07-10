"""Servidor MCP deploy — sidecar kind=mcp_http, GATEWAY-READY (Model C).

24 tools para Git, PR, GitHub Actions, pipeline CI/CD, ACR e workspace local:
  Git (4):            list_repos, create_branch, list_branches, commit_files
  PR (4):             create_pr, get_pr, merge_pr, list_prs
  Workflow (4):       trigger_workflow, list_workflow_runs, get_workflow_run, cancel_workflow_run
  Deploy (2):         deploy, get_deploy_status
  Pipeline (2):       scaffold_pipeline, get_pipeline_templates
  ACR (3):            setup_repo, acr_build, list_acr_images
  Healthcheck (1):    ensure_all_repos_healthy
  Local Workspace (4): get_repos_root, set_repos_root, list_local_repos, clone_repo

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
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: deploy-mcp fala com um BACKEND (GitHub REST API + ACR) via o GitHubClient
(src/knowledge/github_client.py) — o cliente de backend do serviço (Bearer = PAT).
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

from ..config.settings import NAMESPACE, DeploySettings, get_settings
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
    get_pipeline_templates,
    get_pr,
    get_repos_root,
    get_workflow_run,
    list_acr_images,
    list_branches,
    list_local_repos,
    list_prs,
    list_repos,
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
}

assert set(_POLICY.keys()) == set(_TOOL_SCHEMAS.keys()), "_POLICY cobre todas as tools"  # noqa: S101

# Injeta capability + os 3 campos de policy em cada entrada de _TOOL_SCHEMAS,
# para que /mcp/tools/list os emita (o gateway lê estes campos, CI-2).
for _name, _meta in _TOOL_SCHEMAS.items():
    _meta["capability"] = f"{NAMESPACE}.{_name}"
    _meta.update(_POLICY[_name])

# Tools encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless). deploy-mcp
# não tem tool de status/health (o liveness é o endpoint /v1/health), então vazio.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredo NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

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
            payload = _dispatch(name, arguments, settings, client)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error: %s", name)
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────
def build_server() -> tuple[Any, DeploySettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings, o GitHubClient e o sidecar HTTP."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")

    client = GitHubClient(settings)
    http_app = _build_http_app(settings, client)
    _log.info(
        "deploy_mcp_ready tools=%d github_org=%s acr_registry=%s",
        len(_TOOL_SCHEMAS),
        settings.github_org,
        settings.acr_registry,
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
        args = arguments or {}
        try:
            payload = _dispatch(name, args, settings, client)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
            _log.exception("tool_internal_error: %s", name)
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
