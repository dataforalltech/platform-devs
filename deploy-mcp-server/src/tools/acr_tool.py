"""Tools de gerenciamento de ACR e setup centralizado de repositórios.

Tools: setup_repo, acr_build, list_acr_images

O deploy-mcp é a fonte única de credenciais do ACR para o ecossistema.
Cada repo não precisa mais configurar ACR_USERNAME/PASSWORD manualmente:
basta chamar setup_repo uma vez e o deploy-mcp propaga tudo via API.

setup_repo:       Injeta ACR_USERNAME, ACR_PASSWORD e IMAGE_NAME no repo
                  alvo como GitHub Actions secrets/variables. Elimina
                  configuração manual por repo.

acr_build:        Build local + push direto para o ACR sem GitHub Actions.
                  Útil para deploy imediato sem esperar workflow.

list_acr_images:  Lista tags disponíveis de uma imagem no ACR.
"""

from __future__ import annotations

import datetime
import subprocess
from typing import Any

from ..config.settings import DeploySettings
from ..knowledge.github_client import GitHubClient, GitHubClientError


# ─────────────────────────────────────────────────────────────────────────── #
# setup_repo                                                                   #
# ─────────────────────────────────────────────────────────────────────────── #

def setup_repo(
    client: GitHubClient,
    settings: DeploySettings,
    repo: str,
    image_name: str,
    portainer_webhook: str | None = None,
    github_token: str | None = None,
) -> dict[str, Any]:
    """Configura um repositório para deploy automático no ACR.

    Propaga as credenciais ACR do deploy-mcp como secrets do GitHub Actions
    no repo alvo — elimina configuração manual de cada repo.

    Secrets definidos (lidos do deploy-mcp .env):
      ACR_USERNAME         — DEPLOY_ACR_USERNAME
      ACR_PASSWORD         — DEPLOY_ACR_PASSWORD
      PORTAINER_WEBHOOK_URL — (opcional, se informado)
      TOKEN_GITHUB          — (opcional, se informado)

    Variáveis definidas:
      IMAGE_NAME           — nome da imagem no ACR (ex: platform-analytics)

    Args:
        repo: Nome do repo (owner/name ou só name — usa DEPLOY_GITHUB_ORG).
        image_name: Nome da imagem Docker no ACR (ex: platform-analytics).
        portainer_webhook: URL do webhook do Portainer para este repo (opcional).
        github_token: PAT para builds com dependências privadas (opcional).
    """
    if not settings.acr_username or not settings.acr_password:
        return {
            "error": "ConfigError",
            "tool": "setup_repo",
            "details": (
                "DEPLOY_ACR_USERNAME e DEPLOY_ACR_PASSWORD precisam estar configurados "
                "no deploy-mcp (.env ou variáveis de ambiente) para propagar credenciais. "
                "Configure-os uma vez no deploy-mcp e chame setup_repo para cada repo."
            ),
        }

    configured: list[dict] = []
    errors: list[dict] = []

    # ── Secrets ────────────────────────────────────────────────────────────── #
    secrets: dict[str, str] = {
        "ACR_USERNAME": settings.acr_username,
        "ACR_PASSWORD": settings.acr_password,
    }
    if portainer_webhook:
        secrets["PORTAINER_WEBHOOK_URL"] = portainer_webhook
    if github_token:
        secrets["TOKEN_GITHUB"] = github_token

    for secret_name, secret_value in secrets.items():
        try:
            client.set_repo_secret(repo, secret_name, secret_value)
            configured.append({"type": "secret", "name": secret_name, "status": "ok"})
        except GitHubClientError as exc:
            errors.append({"type": "secret", "name": secret_name, "error": str(exc)})

    # ── Variables ──────────────────────────────────────────────────────────── #
    try:
        client.set_repo_variable(repo, "IMAGE_NAME", image_name)
        configured.append(
            {"type": "variable", "name": "IMAGE_NAME", "value": image_name, "status": "ok"}
        )
    except GitHubClientError as exc:
        errors.append({"type": "variable", "name": "IMAGE_NAME", "error": str(exc)})

    success = len(errors) == 0
    return {
        "repo": repo,
        "image_name": image_name,
        "registry": f"{settings.acr_registry}/{settings.acr_namespace}/{image_name}",
        "configured": configured,
        "errors": errors,
        "success": success,
        "next_step": (
            f"trigger_workflow(repo='{repo}', workflow_id='deploy.yml', ref='master') "
            "para disparar o build e push no ACR."
        )
        if success
        else "Corrija os erros e chame setup_repo novamente.",
    }


# ─────────────────────────────────────────────────────────────────────────── #
# acr_build                                                                    #
# ─────────────────────────────────────────────────────────────────────────── #

def acr_build(
    settings: DeploySettings,
    repo_path: str,
    image_name: str,
    tag: str | None = None,
    dockerfile: str = "Dockerfile",
    push: bool = True,
) -> dict[str, Any]:
    """Constrói e empurra uma imagem Docker para o ACR localmente.

    Usa o docker CLI local — não depende de GitHub Actions.
    Credenciais ACR vêm do deploy-mcp (DEPLOY_ACR_USERNAME/PASSWORD).

    Fluxo: docker login → docker build (tags :vX + :latest) → docker push

    Args:
        repo_path: Caminho absoluto do repositório com o Dockerfile.
        image_name: Nome da imagem (ex: platform-analytics).
        tag: Tag da imagem. Default: v3.{YYYYMMDD}-{git_sha7}.
        dockerfile: Caminho do Dockerfile relativo a repo_path. Default: Dockerfile.
        push: Se True, empurra para o ACR após o build. Default: True.
    """
    if not settings.acr_username or not settings.acr_password:
        return {
            "error": "ConfigError",
            "tool": "acr_build",
            "details": "DEPLOY_ACR_USERNAME e DEPLOY_ACR_PASSWORD são obrigatórios.",
        }

    registry = settings.acr_registry
    namespace = settings.acr_namespace
    image_base = f"{registry}/{namespace}/{image_name}"
    steps: list[dict] = []

    # ── Resolve tag ────────────────────────────────────────────────────────── #
    if not tag:
        date_str = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d")
        try:
            sha_result = subprocess.run(
                ["git", "rev-parse", "--short=7", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=5,
            )
            sha7 = sha_result.stdout.strip() if sha_result.returncode == 0 else "local"
        except Exception:  # noqa: BLE001
            sha7 = "local"
        tag = f"v3.{date_str}-{sha7}"

    full_image = f"{image_base}:{tag}"
    latest_image = f"{image_base}:latest"

    # ── docker login ───────────────────────────────────────────────────────── #
    try:
        login = subprocess.run(
            ["docker", "login", registry, "-u", settings.acr_username, "--password-stdin"],
            input=settings.acr_password,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if login.returncode != 0:
            return {
                "error": "DockerLoginError",
                "tool": "acr_build",
                "details": login.stderr.strip(),
            }
        steps.append({"step": "docker_login", "registry": registry, "status": "ok"})
    except FileNotFoundError:
        return {
            "error": "DockerNotFound",
            "tool": "acr_build",
            "details": "Docker CLI não encontrado no PATH. Instale o Docker Desktop.",
        }
    except subprocess.TimeoutExpired:
        return {
            "error": "Timeout",
            "tool": "acr_build",
            "details": "docker login demorou mais de 30s.",
        }

    # ── docker build ───────────────────────────────────────────────────────── #
    build_cmd = [
        "docker", "build",
        "-t", full_image,
        "-t", latest_image,
        "-f", dockerfile,
        ".",
    ]
    try:
        build = subprocess.run(
            build_cmd,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=600,
        )
        if build.returncode != 0:
            return {
                "error": "DockerBuildError",
                "tool": "acr_build",
                "details": (build.stderr or build.stdout).strip()[-3000:],
                "steps": steps,
            }
        steps.append({"step": "docker_build", "image": full_image, "status": "ok"})
    except subprocess.TimeoutExpired:
        return {
            "error": "Timeout",
            "tool": "acr_build",
            "details": "docker build demorou mais de 10 minutos.",
            "steps": steps,
        }

    # ── docker push ────────────────────────────────────────────────────────── #
    if push:
        for img in [full_image, latest_image]:
            try:
                push_result = subprocess.run(
                    ["docker", "push", img],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if push_result.returncode != 0:
                    return {
                        "error": "DockerPushError",
                        "tool": "acr_build",
                        "details": push_result.stderr.strip()[-3000:],
                        "steps": steps,
                    }
                steps.append({"step": "docker_push", "image": img, "status": "ok"})
            except subprocess.TimeoutExpired:
                return {
                    "error": "Timeout",
                    "tool": "acr_build",
                    "details": f"docker push {img} demorou mais de 5 minutos.",
                    "steps": steps,
                }

    return {
        "success": True,
        "image": full_image,
        "image_latest": latest_image,
        "tag": tag,
        "registry": registry,
        "pushed": push,
        "steps": steps,
    }


# ─────────────────────────────────────────────────────────────────────────── #
# list_acr_images                                                              #
# ─────────────────────────────────────────────────────────────────────────── #

def list_acr_images(
    client: GitHubClient,
    settings: DeploySettings,
    service_name: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Lista as tags disponíveis de uma imagem no ACR.

    Args:
        service_name: Nome do serviço/imagem (ex: platform-analytics).
        limit: Máximo de tags a retornar. Default: 20.
    """
    if not settings.acr_username or not settings.acr_password:
        return {
            "error": "ConfigError",
            "tool": "list_acr_images",
            "details": "DEPLOY_ACR_USERNAME e DEPLOY_ACR_PASSWORD são obrigatórios.",
        }

    try:
        tags = client.list_acr_tags(
            registry=settings.acr_registry,
            namespace=settings.acr_namespace,
            service_name=service_name,
            username=settings.acr_username,
            password=settings.acr_password,
            limit=limit,
        )
        return {
            "service": service_name,
            "image": f"{settings.acr_registry}/{settings.acr_namespace}/{service_name}",
            "tags": tags,
            "count": len(tags),
        }
    except GitHubClientError as exc:
        return {"error": type(exc).__name__, "tool": "list_acr_images", "details": str(exc)}
