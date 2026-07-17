"""Catálogo de tools + dispatcher do domínio *devops* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `devops-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler, aqui exposto como ``dispatch``). O que ficou de
FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant plumbing) — isso é
responsabilidade do AGREGADOR (`src/server/mcp_server.py`), compartilhado por todos os
domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.devops_<op>`` (namespace do server consolidado +
    nome de tool já prefixado pelo domínio — o gateway não deriva por nome, então a
    capability é o id estável).
  * ``required_scope`` passa a ``devops:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool do domínio, só troca o antigo prefixo de namespace ``devops-mcp`` pelo
    domínio canônico ``devops``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_artifact``); o ``plugin.register()`` prefixa (``devops_save_artifact``) e o
    ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim a
    lógica de roteamento copiada do server-fonte fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import DevopsStore
from .tools import (
    delete_artifact,
    delete_deployment,
    delete_environment,
    delete_pipeline,
    delete_service_config,
    generate_docker_compose,
    generate_dockerfile,
    generate_github_actions_pipeline,
    generate_helm_chart,
    generate_kubernetes_manifest,
    generate_terraform_module,
    get_artifact,
    get_deployment,
    get_environment,
    get_pipeline,
    get_service_config,
    list_artifacts,
    list_deployments,
    list_environments,
    list_pipelines,
    list_service_configs,
    save_artifact,
    save_deployment,
    save_pipeline,
    set_environment,
    set_service_config,
    update_deployment_status,
    update_pipeline,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "devops"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <namespace>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consultas (list/get) usam :read;
# mutações (save/set/update/delete) usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props}
    if required:
        s["required"] = required
    return s


def _meta(cap: str, scope: str, rtype: str, domain: str, desc: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": desc,
        # capability = <namespace do server consolidado>.<domínio>_<op>
        "capability": f"devteam-mcp.{DOMAIN}_{cap}",
        # required_scope = <domínio>:<recurso>:<ação> (least-privilege por-tool intacto)
        "required_scope": f"{DOMAIN}:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "devops",
        "Persiste um artefato de infra-as-code (Dockerfile/pipeline/chart/manifesto) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: dockerfile|github_actions|gitlab_ci|helm_chart|"
                        "k8s_manifest|terraform|compose|ansible|kustomize."
                    ),
                ),
                "target": dict(_STR, description="Alvo (aplicação/serviço/módulo)."),
                "content": dict(_STR, description="Conteúdo do arquivo IaC gerado pelo agente."),
                "tool": dict(_STR, description="Ferramenta (docker/helm/kustomize/...; opcional)."),
                "spec": dict(_OBJ, description="Parâmetros/inputs do artefato (opcional)."),
                "status": dict(_STR, description="Status do artefato (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "devops",
        "Lista artefatos IaC persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_artifact": _meta(
        "get_artifact",
        "artifact:read",
        "artifact",
        "devops",
        "Retorna um artefato de infra-as-code persistido (Dockerfile/pipeline/chart/manifesto) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "devops",
        "Remove (soft-delete) um artefato de infra-as-code persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Pipelines ──────────────────────────────────────────────────────────── #
    "save_pipeline": _meta(
        "save_pipeline",
        "pipeline:write",
        "pipeline",
        "devops",
        "Persiste uma pipeline de CI/CD fornecida pelo agente (stages/triggers vêm do agente).",
        _schema(
            {
                "application": dict(_STR, description="Aplicação alvo."),
                "provider": dict(_STR, description="Provedor (github_actions/gitlab_ci/jenkins/...)."),
                "content": dict(_OBJ, description="Conteúdo da pipeline (stages/triggers/jobs)."),
                "status": dict(_STR, description="Status da pipeline (opcional)."),
            },
            required=["application", "provider"],
        ),
    ),
    "list_pipelines": _meta(
        "list_pipelines",
        "pipeline:read",
        "pipeline",
        "devops",
        "Lista pipelines persistidas, com filtros opcionais.",
        _schema(
            {
                "application": dict(_STR, description="Filtrar por aplicação (opcional)."),
                "provider": dict(_STR, description="Filtrar por provedor (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_pipeline": _meta(
        "get_pipeline",
        "pipeline:read",
        "pipeline",
        "devops",
        "Retorna uma pipeline de CI/CD persistida (stages/triggers/jobs) por id.",
        _schema({"id": dict(_INT, description="Id da pipeline.")}, required=["id"]),
    ),
    "update_pipeline": _meta(
        "update_pipeline",
        "pipeline:write",
        "pipeline",
        "devops",
        "Atualiza campos mutáveis de uma pipeline (provider/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da pipeline."),
                "provider": dict(_STR, description="Novo provedor (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_pipeline": _meta(
        "delete_pipeline",
        "pipeline:write",
        "pipeline",
        "devops",
        "Remove (soft-delete) uma pipeline de CI/CD persistida por id; idempotente.",
        _schema({"id": dict(_INT, description="Id da pipeline.")}, required=["id"]),
    ),
    # ── Deployments ────────────────────────────────────────────────────────── #
    "save_deployment": _meta(
        "save_deployment",
        "deployment:write",
        "deployment",
        "operational",
        "Persiste um deploy. Se strategy não vier, recomenda-a deterministicamente do ambiente.",
        _schema(
            {
                "application": dict(_STR, description="Aplicação alvo."),
                "environment": dict(_STR, description="Ambiente (dev/hml/prod)."),
                "version": dict(_STR, description="Versão / image tag."),
                "strategy": dict(
                    _STR, description="Estratégia (rolling/blue_green/canary/recreate; calculada se ausente)."
                ),
                "notes": dict(_STR, description="Notas do deploy (opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
                "status": dict(_STR, description="Status (default pending)."),
            },
            required=["application", "environment", "version"],
        ),
    ),
    "list_deployments": _meta(
        "list_deployments",
        "deployment:read",
        "deployment",
        "operational",
        "Lista deployments persistidos, com filtros opcionais.",
        _schema(
            {
                "application": dict(_STR, description="Filtrar por aplicação (opcional)."),
                "environment": dict(_STR, description="Filtrar por ambiente (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_deployment": _meta(
        "get_deployment",
        "deployment:read",
        "deployment",
        "operational",
        "Retorna um deployment persistido (aplicação/ambiente/versão/estratégia/status) por id.",
        _schema({"id": dict(_INT, description="Id do deployment.")}, required=["id"]),
    ),
    "update_deployment_status": _meta(
        "update_deployment_status",
        "deployment:write",
        "deployment",
        "operational",
        "Atualiza o status de um deployment (ex.: pending→running→succeeded/failed).",
        _schema(
            {
                "id": dict(_INT, description="Id do deployment."),
                "status": dict(_STR, description="Novo status."),
            },
            required=["id", "status"],
        ),
    ),
    "delete_deployment": _meta(
        "delete_deployment",
        "deployment:write",
        "deployment",
        "operational",
        "Remove (soft-delete) um deployment persistido por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do deployment.")}, required=["id"]),
    ),
    # ── Environments (upsert por name) ─────────────────────────────────────── #
    "set_environment": _meta(
        "set_environment",
        "environment:write",
        "environment",
        "devops",
        "Registra (upsert) um ambiente/cluster de deploy com a config fornecida.",
        _schema(
            {
                "name": dict(_STR, description="Nome do ambiente (chave natural única)."),
                "kind": dict(_STR, description="Tipo (kubernetes/vm/serverless/docker/bare_metal)."),
                "region": dict(_STR, description="Região (opcional)."),
                "config": dict(_OBJ, description="Config do ambiente (cluster/namespace/limites)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["name", "kind"],
        ),
    ),
    "list_environments": _meta(
        "list_environments",
        "environment:read",
        "environment",
        "devops",
        "Lista ambientes registrados, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_environment": _meta(
        "get_environment",
        "environment:read",
        "environment",
        "devops",
        "Retorna um ambiente/cluster de deploy registrado (tipo/região/config) pela chave natural name.",
        _schema({"name": dict(_STR, description="Nome do ambiente.")}, required=["name"]),
    ),
    "delete_environment": _meta(
        "delete_environment",
        "environment:write",
        "environment",
        "devops",
        "Remove (soft-delete) um ambiente/cluster de deploy registrado pela chave natural name; idempotente.",
        _schema({"name": dict(_STR, description="Nome do ambiente.")}, required=["name"]),
    ),
    # ── Service Configs (upsert por service) ───────────────────────────────── #
    "set_service_config": _meta(
        "set_service_config",
        "service_config:write",
        "service_config",
        "devops",
        "Define (upsert) a config de devops de um serviço com os settings fornecidos.",
        _schema(
            {
                "service": dict(_STR, description="Serviço alvo (chave natural única)."),
                "settings": dict(_OBJ, description="Settings (replicas/resources/env)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["service", "settings"],
        ),
    ),
    "list_service_configs": _meta(
        "list_service_configs",
        "service_config:read",
        "service_config",
        "devops",
        "Lista service configs persistidas, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_service_config": _meta(
        "get_service_config",
        "service_config:read",
        "service_config",
        "devops",
        "Retorna a config de devops de um serviço.",
        _schema({"service": dict(_STR, description="Serviço alvo.")}, required=["service"]),
    ),
    "delete_service_config": _meta(
        "delete_service_config",
        "service_config:write",
        "service_config",
        "devops",
        "Soft-delete da config de devops de um serviço.",
        _schema({"service": dict(_STR, description="Serviço alvo.")}, required=["service"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com
    # :read p/ consultas e :write p/ mutações do estado do tenant. Geradores não
    # LEEM nem GRAVAM estado — só computam conteúdo IaC — então nenhum dos dois
    # cabe. Escolha: nova ação `:generate` sobre resource_type=`artifact` (o mesmo
    # domínio dos artefatos IaC produzidos): least-privilege real (um token só de
    # geração não abre leitura/escrita de artefatos persistidos). data_domain=devops.
    "generate_dockerfile": _meta(
        "generate_dockerfile",
        "artifact:generate",
        "artifact",
        "devops",
        "Gera um Dockerfile (multi-stage quando faz sentido) determinístico a partir da spec.",
        _schema(
            {
                "language": dict(_STR, description="Linguagem: python|node|go|java."),
                "framework": dict(_STR, description="Framework (opcional)."),
                "app_dir": dict(_STR, description="Diretório da aplicação (default '.')."),
                "port": dict(_INT, description="Porta exposta (opcional)."),
                "package_manager": dict(_STR, description="Gerenciador de pacotes (opcional)."),
                "version": dict(_STR, description="Versão do runtime base (opcional)."),
                "extra_system_deps": dict(_ARR, description="Pacotes de sistema extras (opcional)."),
            },
            required=["language"],
        ),
    ),
    "generate_docker_compose": _meta(
        "generate_docker_compose",
        "artifact:generate",
        "artifact",
        "devops",
        "Gera um docker-compose.yml determinístico a partir da lista de serviços.",
        _schema(
            {
                "services": dict(
                    _ARR,
                    description="Serviços [{name,image?,build?,ports?,environment?,depends_on?}].",
                ),
                "version": dict(_STR, description="Versão do compose (default '3.9')."),
                "networks": dict(_ARR, description="Nomes de redes a declarar (opcional)."),
            },
            required=["services"],
        ),
    ),
    "generate_kubernetes_manifest": _meta(
        "generate_kubernetes_manifest",
        "artifact:generate",
        "artifact",
        "devops",
        "Gera um manifesto Kubernetes (Deployment|Service|Ingress|ConfigMap) determinístico.",
        _schema(
            {
                "kind": dict(_STR, description="Deployment|Service|Ingress|ConfigMap."),
                "name": dict(_STR, description="Nome do recurso."),
                "image": dict(_STR, description="Imagem do container (opcional)."),
                "replicas": dict(_INT, description="Réplicas (default 1)."),
                "port": dict(_INT, description="Porta (opcional)."),
                "env": dict(_OBJ, description="Variáveis de ambiente (opcional)."),
                "resources": dict(_OBJ, description="requests/limits de recursos (opcional)."),
                "namespace": dict(_STR, description="Namespace (opcional)."),
            },
            required=["kind", "name"],
        ),
    ),
    "generate_terraform_module": _meta(
        "generate_terraform_module",
        "artifact:generate",
        "artifact",
        "devops",
        "Gera HCL (main.tf + variables/outputs agregados) determinístico para aws|gcp|azure.",
        _schema(
            {
                "provider": dict(_STR, description="Provider: aws|gcp|azure."),
                "resources": dict(_ARR, description="Recursos [{type,name,args}]."),
                "variables": dict(_OBJ, description="Variáveis do módulo (opcional)."),
                "outputs": dict(_OBJ, description="Outputs do módulo (opcional)."),
            },
            required=["provider", "resources"],
        ),
    ),
    "generate_helm_chart": _meta(
        "generate_helm_chart",
        "artifact:generate",
        "artifact",
        "devops",
        "Gera um Helm chart multi-arquivo (Chart.yaml/values.yaml/templates) determinístico.",
        _schema(
            {
                "name": dict(_STR, description="Nome do chart/app."),
                "image": dict(_STR, description="Repositório da imagem."),
                "port": dict(_INT, description="Porta do serviço (default 80)."),
                "values": dict(_OBJ, description="Valores extras (opcional)."),
                "app_version": dict(_STR, description="appVersion / tag (default 1.0.0)."),
            },
            required=["name", "image"],
        ),
    ),
    "generate_github_actions_pipeline": _meta(
        "generate_github_actions_pipeline",
        "artifact:generate",
        "artifact",
        "devops",
        "Gera um workflow do GitHub Actions determinístico a partir de jobs/steps.",
        _schema(
            {
                "name": dict(_STR, description="Nome do workflow."),
                "on": dict(_ARR, description="Gatilhos (default [push, pull_request])."),
                "jobs": dict(_ARR, description="Jobs [{name,runs_on?,steps:[{name?,uses?,run?,with?}]}]."),
            },
            required=["name", "jobs"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: DevopsStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). ``name`` é o nome de op SEM prefixo de
    domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_dockerfile":
        return generate_dockerfile(args)
    if name == "generate_docker_compose":
        return generate_docker_compose(args)
    if name == "generate_kubernetes_manifest":
        return generate_kubernetes_manifest(args)
    if name == "generate_terraform_module":
        return generate_terraform_module(args)
    if name == "generate_helm_chart":
        return generate_helm_chart(args)
    if name == "generate_github_actions_pipeline":
        return generate_github_actions_pipeline(args)
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            tool=args.get("tool"),
            spec=args.get("spec"),
            status=args.get("status"),
        )
    if name == "list_artifacts":
        return await list_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_artifact":
        return await get_artifact(store, artifact_id=args["id"])
    if name == "delete_artifact":
        return await delete_artifact(store, artifact_id=args["id"])
    # ── Pipelines ──────────────────────────────────────────────────────────── #
    if name == "save_pipeline":
        return await save_pipeline(
            store,
            application=args["application"],
            provider=args["provider"],
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "list_pipelines":
        return await list_pipelines(
            store,
            application=args.get("application"),
            provider=args.get("provider"),
            status=args.get("status"),
        )
    if name == "get_pipeline":
        return await get_pipeline(store, pipeline_id=args["id"])
    if name == "update_pipeline":
        return await update_pipeline(
            store,
            pipeline_id=args["id"],
            provider=args.get("provider"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_pipeline":
        return await delete_pipeline(store, pipeline_id=args["id"])
    # ── Deployments ────────────────────────────────────────────────────────── #
    if name == "save_deployment":
        return await save_deployment(
            store,
            application=args["application"],
            environment=args["environment"],
            version=args["version"],
            strategy=args.get("strategy"),
            notes=args.get("notes"),
            meta=args.get("meta"),
            status=args.get("status", "pending"),
        )
    if name == "list_deployments":
        return await list_deployments(
            store,
            application=args.get("application"),
            environment=args.get("environment"),
            status=args.get("status"),
        )
    if name == "get_deployment":
        return await get_deployment(store, deployment_id=args["id"])
    if name == "update_deployment_status":
        return await update_deployment_status(store, deployment_id=args["id"], status=args["status"])
    if name == "delete_deployment":
        return await delete_deployment(store, deployment_id=args["id"])
    # ── Environments ───────────────────────────────────────────────────────── #
    if name == "set_environment":
        return await set_environment(
            store,
            name=args["name"],
            kind=args["kind"],
            region=args.get("region"),
            config=args.get("config"),
            status=args.get("status"),
        )
    if name == "list_environments":
        return await list_environments(store, kind=args.get("kind"), status=args.get("status"))
    if name == "get_environment":
        return await get_environment(store, name=args["name"])
    if name == "delete_environment":
        return await delete_environment(store, name=args["name"])
    # ── Service Configs ────────────────────────────────────────────────────── #
    if name == "set_service_config":
        return await set_service_config(
            store, service=args["service"], settings=args["settings"], status=args.get("status")
        )
    if name == "list_service_configs":
        return await list_service_configs(store, status=args.get("status"))
    if name == "get_service_config":
        return await get_service_config(store, service=args["service"])
    if name == "delete_service_config":
        return await delete_service_config(store, service=args["service"])
    raise KeyError(name)
