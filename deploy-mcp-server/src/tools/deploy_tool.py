"""Tools de alto nível para deploy.

Tools: deploy, get_deploy_status

Mapeia ambiente → workflow → ref adequado para o ecossistema dataforalltech:
  dev  → cd-dev.yml  → branch develop
  hml  → cd-hml.yml  → branch release/<versao>
  prod → cd-prod.yml → tag v<semver>  (ou deploy.yml via workflow_dispatch)
"""

from __future__ import annotations

from ..knowledge.github_client import GitHubClient, GitHubClientError

# Mapeamento ambiente → (workflow_file, branch_default)
_ENV_CONFIG: dict[str, dict] = {
    "dev": {
        "workflow": "cd-dev.yml",
        "default_ref": "develop",
        "ref_hint": "develop",
    },
    "hml": {
        "workflow": "cd-hml.yml",
        "default_ref": None,  # exige release/<version>
        "ref_hint": "release/1.0.0 (branch release/*)",
    },
    "prod": {
        "workflow": "cd-prod.yml",
        "default_ref": None,  # exige tag v*.*.*
        "ref_hint": "v1.0.0 (tag semver)",
    },
}


def _error(tool: str, exc: Exception) -> dict:
    return {"error": type(exc).__name__, "tool": tool, "details": str(exc)}


def deploy(
    client: GitHubClient,
    service: str,
    environment: str,
    ref: str | None = None,
    repo: str | None = None,
    inputs: dict[str, str] | None = None,
) -> dict:
    """Dispara o deploy de um serviço para um ambiente.

    Mapeia automaticamente ambiente → workflow → ref:
      dev  → cd-dev.yml   @ develop
      hml  → cd-hml.yml   @ release/<versao>  (ref obrigatório)
      prod → cd-prod.yml  @ v<semver>          (ref obrigatório)

    Args:
        service: Nome do serviço (usado como nome do repo se repo não for informado).
        environment: Ambiente alvo: dev | hml | prod.
        ref: Branch/tag para o dispatch. Obrigatório para hml e prod.
             Para dev o default é 'develop'.
        repo: Nome do repo (se diferente do service).
        inputs: Inputs extras para o workflow_dispatch.
    """
    try:
        if not service or not environment:
            return {
                "error": "ValidationError",
                "tool": "deploy",
                "details": "service e environment são obrigatórios.",
            }

        cfg = _ENV_CONFIG.get(environment)
        if cfg is None:
            return {
                "error": "ValidationError",
                "tool": "deploy",
                "details": (
                    f"environment inválido: {environment!r}. "
                    "Use dev, hml ou prod."
                ),
            }

        actual_ref = ref or cfg["default_ref"]
        if actual_ref is None:
            return {
                "error": "ValidationError",
                "tool": "deploy",
                "details": (
                    f"environment='{environment}' exige ref explícito. "
                    f"Exemplo: {cfg['ref_hint']}"
                ),
            }

        target_repo = repo or service
        result = client.trigger_workflow(
            repo=target_repo,
            workflow_id=cfg["workflow"],
            ref=actual_ref,
            inputs=inputs or {},
        )
        result["environment"] = environment
        result["service"] = service
        return result
    except GitHubClientError as exc:
        return _error("deploy", exc)


def get_deploy_status(
    client: GitHubClient,
    service: str,
    environment: str,
    repo: str | None = None,
    limit: int = 5,
) -> dict:
    """Retorna os últimos runs de deploy para um serviço e ambiente.

    Args:
        service: Nome do serviço (repo).
        environment: Ambiente: dev | hml | prod.
        repo: Nome do repo (se diferente do service).
        limit: Máximo de runs a retornar. Default: 5.
    """
    try:
        if not service or not environment:
            return {
                "error": "ValidationError",
                "tool": "get_deploy_status",
                "details": "service e environment são obrigatórios.",
            }

        cfg = _ENV_CONFIG.get(environment)
        if cfg is None:
            return {
                "error": "ValidationError",
                "tool": "get_deploy_status",
                "details": f"environment inválido: {environment!r}. Use dev, hml ou prod.",
            }

        target_repo = repo or service
        runs = client.list_workflow_runs(
            target_repo, workflow_id=cfg["workflow"], limit=min(limit, 20)
        )
        return {
            "service": service,
            "environment": environment,
            "workflow": cfg["workflow"],
            "recent_runs": runs,
            "count": len(runs),
        }
    except GitHubClientError as exc:
        return _error("get_deploy_status", exc)
