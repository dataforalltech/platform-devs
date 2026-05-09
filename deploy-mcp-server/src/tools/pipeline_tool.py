"""Tools de pipeline CI/CD.

Tools: scaffold_pipeline, get_pipeline_templates

scaffold_pipeline instala os workflows padrão do platform-service-template
em qualquer repositório via GitHub Contents API.

Os templates usam variáveis/secrets do GitHub (IMAGE_NAME, ACR_USERNAME, etc.)
configuradas no repo — o YAML é 100% genérico entre serviços.
"""

from __future__ import annotations

from pathlib import Path

from ..knowledge.github_client import GitHubClient, GitHubClientError

# Diretório com os templates embedded no pacote
_TEMPLATES_DIR = Path(__file__).parent.parent / "knowledge" / "pipeline_templates"

# Catálogo de templates disponíveis
_TEMPLATE_CATALOG: list[dict] = [
    {
        "name": "ci",
        "file": "ci.yml",
        "description": (
            "Lint (ruff/black/mypy), security audit (pip-audit), "
            "OpenAPI schema drift (oasdiff), unit tests com postgres+redis."
        ),
        "required_secrets": ["TOKEN_GITHUB", "CODECOV_TOKEN"],
        "required_vars": [],
        "trigger": "push em develop/release/**, pull_request para develop/main/release/**",
    },
    {
        "name": "deploy",
        "file": "deploy.yml",
        "description": (
            "Build Docker image + push ACR + Portainer webhook (prod). "
            "Trigger: CI verde em main ou workflow_dispatch manual."
        ),
        "required_secrets": [
            "TOKEN_GITHUB",
            "ACR_USERNAME",
            "ACR_PASSWORD",
            "PORTAINER_WEBHOOK_URL",
        ],
        "required_vars": ["IMAGE_NAME"],
        "optional_vars": ["SERVICE_INTERNAL_URL"],
        "optional_secrets": ["INTERNAL_API_TOKEN", "SLACK_WEBHOOK"],
        "trigger": "workflow_run CI (main) ou workflow_dispatch",
    },
    {
        "name": "cd-dev",
        "file": "cd-dev.yml",
        "description": (
            "Continuous Delivery → DEV. "
            "Build + push ACR (dev-<sha7>, develop-latest) + Portainer DEV."
        ),
        "required_secrets": [
            "TOKEN_GITHUB",
            "ACR_USERNAME",
            "ACR_PASSWORD",
            "PORTAINER_WEBHOOK_URL",
        ],
        "required_vars": ["IMAGE_NAME"],
        "optional_vars": ["SERVICE_INTERNAL_URL"],
        "trigger": "push em develop",
    },
    {
        "name": "cd-hml",
        "file": "cd-hml.yml",
        "description": (
            "Continuous Delivery → HML. "
            "Build + push ACR (hml-<sha7>, hml-<version>) + Portainer HML + migration polling."
        ),
        "required_secrets": [
            "TOKEN_GITHUB",
            "ACR_USERNAME",
            "ACR_PASSWORD",
            "PORTAINER_WEBHOOK_URL",
            "INTERNAL_API_TOKEN",
        ],
        "required_vars": ["IMAGE_NAME"],
        "optional_vars": ["SERVICE_INTERNAL_URL"],
        "trigger": "push em release/**",
    },
    {
        "name": "cd-prod",
        "file": "cd-prod.yml",
        "description": (
            "Continuous Delivery → PROD. "
            "Build + push ACR (v<semver>, prod-latest) + aprovação manual + Portainer PROD."
        ),
        "required_secrets": [
            "TOKEN_GITHUB",
            "ACR_USERNAME",
            "ACR_PASSWORD",
            "PORTAINER_WEBHOOK_URL",
            "INTERNAL_API_TOKEN",
        ],
        "required_vars": ["IMAGE_NAME", "SERVICE_INTERNAL_URL"],
        "trigger": "push de tag v*.*.*",
        "note": "APROVAÇÃO MANUAL obrigatória — configure Required Reviewers no Environment 'prod'.",
    },
    {
        "name": "pr-validate",
        "file": "pr-validate.yml",
        "description": (
            "Validação de PR via ai-governance MCP. "
            "Posta comentário com resultado (não bloqueia merge por padrão)."
        ),
        "required_secrets": [],
        "required_vars": [],
        "trigger": "pull_request opened/synchronize/reopened para main/develop",
    },
]


def _error(tool: str, exc: Exception) -> dict:
    return {"error": type(exc).__name__, "tool": tool, "details": str(exc)}


def get_pipeline_templates() -> dict:
    """Lista os templates de CI/CD disponíveis para scaffold_pipeline.

    Retorna catálogo com nome, descrição, secrets/variables obrigatórios e trigger.
    """
    return {"templates": _TEMPLATE_CATALOG, "count": len(_TEMPLATE_CATALOG)}


def scaffold_pipeline(
    client: GitHubClient,
    repo: str,
    templates: list[str] | None = None,
    branch: str = "develop",
    commit_message: str | None = None,
) -> dict:
    """Instala workflows padrão do platform-service-template em um repositório.

    Cria/atualiza os arquivos .github/workflows/<template>.yml via commit.
    Os templates são genéricos — não têm valores hardcoded de serviço.
    Variáveis como IMAGE_NAME devem ser configuradas nas Settings do repo no GitHub.

    Args:
        repo: Nome do repo alvo.
        templates: Lista de templates a instalar (ex: ["ci", "cd-dev", "cd-hml"]).
                   Default: instala todos (ci, deploy, cd-dev, cd-hml, cd-prod, pr-validate).
        branch: Branch onde fazer o commit. Default: develop.
        commit_message: Mensagem do commit. Default: mensagem padrão.
    """
    try:
        if not repo:
            return {
                "error": "ValidationError",
                "tool": "scaffold_pipeline",
                "details": "repo é obrigatório.",
            }

        # Resolve quais templates instalar
        available = {t["name"]: t for t in _TEMPLATE_CATALOG}
        requested = templates or list(available.keys())

        invalid = [t for t in requested if t not in available]
        if invalid:
            return {
                "error": "ValidationError",
                "tool": "scaffold_pipeline",
                "details": (
                    f"Templates inválidos: {invalid}. "
                    f"Use get_pipeline_templates para ver os disponíveis."
                ),
            }

        # Lê os arquivos de template
        files_to_commit = []
        missing_templates = []
        for name in requested:
            meta = available[name]
            tpl_path = _TEMPLATES_DIR / meta["file"]
            if not tpl_path.exists():
                missing_templates.append(name)
                continue
            content = tpl_path.read_text(encoding="utf-8")
            files_to_commit.append(
                {
                    "path": f".github/workflows/{meta['file']}",
                    "content": content,
                }
            )

        if missing_templates:
            return {
                "error": "TemplateNotFound",
                "tool": "scaffold_pipeline",
                "details": f"Templates sem arquivo embedded: {missing_templates}",
            }

        if not files_to_commit:
            return {
                "error": "NoFilesToCommit",
                "tool": "scaffold_pipeline",
                "details": "Nenhum arquivo para commitar.",
            }

        msg = commit_message or (
            f"ci: instala workflows padrão platform-service-template ({', '.join(requested)})"
        )

        result = client.commit_files(
            repo=repo,
            branch=branch,
            message=msg,
            files=files_to_commit,
        )

        return {
            "committed": True,
            "repo": repo,
            "branch": branch,
            "sha": result.get("sha"),
            "url": result.get("url"),
            "files_installed": [f["path"] for f in files_to_commit],
            "count": len(files_to_commit),
            "next_steps": [
                "Configure secrets no repo: Settings → Secrets and variables → Actions",
                "Configure IMAGE_NAME como variável: Settings → Secrets and variables → Actions → Variables",
                "Para cd-prod.yml: configure Required Reviewers no Environment 'prod'",
            ],
        }
    except GitHubClientError as exc:
        return _error("scaffold_pipeline", exc)
    except OSError as exc:
        return _error("scaffold_pipeline", exc)
