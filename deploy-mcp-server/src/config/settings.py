"""Deploy MCP Server — configuração via variáveis de ambiente.

Prefixo: DEPLOY_
Exceção: DEPLOY_GITHUB_TOKEN (padrão explícito para não colidir com GITHUB_TOKEN do Actions runner).

Exemplo de uso:
    export DEPLOY_GITHUB_TOKEN=ghp_xxxx
    export DEPLOY_GITHUB_ORG=dataforalltech
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeploySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEPLOY_",
        env_file=".env",
        extra="ignore",
    )

    # ── GitHub ─────────────────────────────────────────────────────────────── #
    github_token: str = Field(
        description="GitHub PAT com escopos repo + workflow (obrigatório)."
    )
    github_org: str = Field(
        default="dataforalltech",
        description="Organização GitHub padrão usada quando repo não tem owner/.",
    )
    default_base_branch: str = Field(
        default="develop",
        description="Branch base padrão para PRs (develop, main, etc.).",
    )

    # ── Azure Container Registry ────────────────────────────────────────────── #
    acr_registry: str = Field(
        default="d4all.azurecr.io",
        description="Hostname do ACR (sem https://).",
    )
    acr_namespace: str = Field(
        default="dataforall/3.0",
        description="Namespace de imagens dentro do ACR.",
    )
    acr_username: str | None = Field(
        default=None,
        description="Service Principal client ID com role AcrPull (opcional — para list_acr_tags).",
    )
    acr_password: str | None = Field(
        default=None,
        description="Service Principal client secret (opcional — para list_acr_tags).",
    )

    # ── Pipeline templates ──────────────────────────────────────────────────── #
    platform_template_repo: str = Field(
        default="platform-devs",
        description="Nome do repo de template canônico (scaffold_pipeline usa como referência).",
    )

    # ── Local workspace ─────────────────────────────────────────────────────── #
    repos_root: str = Field(
        default="",
        description=(
            "Pasta raiz onde os repositorios ficam clonados localmente. "
            "Se vazio, tenta ler do config-mcp (workspace.REPOS_ROOT) em runtime. "
            "Env var: DEPLOY_REPOS_ROOT"
        ),
    )

    def get_repos_root_path(self) -> "Path | None":
        """Retorna o Path resolvido do repos_root, ou None se nao configurado."""
        from pathlib import Path

        if self.repos_root:
            return Path(self.repos_root).expanduser().resolve()

        # Fallback: variaveis de ambiente comuns
        for env_key in ("REPOS_ROOT", "WORKSPACE_REPOS_ROOT"):
            val = __import__("os").environ.get(env_key)
            if val:
                return Path(val).expanduser().resolve()

        return None


@lru_cache(maxsize=1)
def get_settings() -> DeploySettings:
    return DeploySettings()
