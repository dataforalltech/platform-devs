"""Operações diretas e explícitas no Azure Container Registry.

O módulo não cria workflows nem propaga credenciais para repositórios. Build e
push têm efeito externo e só podem ser chamados após autorização humana.
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from typing import Any

from ..config.settings import DeploySettings
from ..knowledge.github_client import GitHubClient, GitHubClientError


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def acr_build(
    settings: DeploySettings,
    repo_path: str,
    image_name: str,
    tag: str | None = None,
    dockerfile: str = "Dockerfile",
    push: bool = True,
) -> dict[str, Any]:
    """Constrói e, quando autorizado, envia uma única tag imutável ao ACR.

    A tool não cria `latest`. O retorno identifica lacunas de supply chain que o
    operador ainda precisa evidenciar (SBOM, provenance e scan).
    """
    root = Path(repo_path).resolve()
    dockerfile_path = (root / dockerfile).resolve()
    if not root.is_dir() or root not in dockerfile_path.parents:
        return {
            "error": "ValidationError",
            "tool": "acr_build",
            "details": "repo_path ou dockerfile fora do repositório.",
        }
    if not dockerfile_path.is_file():
        return {
            "error": "ValidationError",
            "tool": "acr_build",
            "details": f"Dockerfile não encontrado: {dockerfile_path}",
        }
    if push and (not settings.acr_username or not settings.acr_password):
        return {
            "error": "ConfigError",
            "tool": "acr_build",
            "details": "DEPLOY_ACR_USERNAME/PASSWORD são obrigatórios para push.",
        }

    try:
        revision = _run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, timeout=10)
        sha = revision.stdout.strip() if revision.returncode == 0 else "unversioned"
        if tag is None:
            date = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d")
            tag = f"v3.{date}-{sha}"
        if tag.lower() == "latest":
            return {
                "error": "ValidationError",
                "tool": "acr_build",
                "details": "A tag mutável 'latest' é proibida.",
            }

        image = f"{settings.acr_registry}/{settings.acr_namespace}/{image_name}:{tag}"
        steps: list[dict[str, str]] = []

        if push:
            login = subprocess.run(
                [
                    "docker",
                    "login",
                    settings.acr_registry,
                    "-u",
                    settings.acr_username,
                    "--password-stdin",
                ],
                input=settings.acr_password,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if login.returncode != 0:
                return {
                    "error": "DockerLoginError",
                    "tool": "acr_build",
                    "details": login.stderr.strip()[-2000:],
                }
            steps.append({"step": "docker_login", "status": "ok"})

        build = _run(
            ["docker", "build", "-t", image, "-f", str(dockerfile_path), "."],
            cwd=root,
            timeout=600,
        )
        if build.returncode != 0:
            return {
                "error": "DockerBuildError",
                "tool": "acr_build",
                "details": (build.stderr or build.stdout).strip()[-3000:],
                "steps": steps,
            }
        steps.append({"step": "docker_build", "status": "ok", "image": image})

        if push:
            pushed = _run(["docker", "push", image], timeout=300)
            if pushed.returncode != 0:
                return {
                    "error": "DockerPushError",
                    "tool": "acr_build",
                    "details": pushed.stderr.strip()[-3000:],
                    "steps": steps,
                }
            steps.append({"step": "docker_push", "status": "ok", "image": image})

        inspect = _run(
            ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
            timeout=30,
        )
        repo_digests = inspect.stdout.strip() if inspect.returncode == 0 else "[]"
        return {
            "success": True,
            "image": image,
            "tag": tag,
            "source_revision": sha,
            "pushed": push,
            "repo_digests": repo_digests,
            "steps": steps,
            "evidence_gaps": [
                "SBOM não é gerada por esta tool",
                "provenance/attestation não é gerada por esta tool",
                "scan da imagem não é executado por esta tool",
            ],
        }
    except FileNotFoundError:
        return {
            "error": "ExecutableNotFound",
            "tool": "acr_build",
            "details": "git ou docker não encontrado no PATH.",
        }
    except subprocess.TimeoutExpired as exc:
        return {"error": "Timeout", "tool": "acr_build", "details": str(exc)}


def list_acr_images(
    client: GitHubClient,
    settings: DeploySettings,
    service_name: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Lista tags disponíveis de uma imagem no ACR, sem alterar estado."""
    if not settings.acr_username or not settings.acr_password:
        return {
            "error": "ConfigError",
            "tool": "list_acr_images",
            "details": "DEPLOY_ACR_USERNAME/PASSWORD são obrigatórios.",
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
        return {
            "error": type(exc).__name__,
            "tool": "list_acr_images",
            "details": str(exc),
        }
