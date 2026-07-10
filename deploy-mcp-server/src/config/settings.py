"""Settings do deploy-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`deploy-mcp` fala com um BACKEND (GitHub REST API + ACR) via o `GitHubClient`
(src/knowledge/github_client.py) — este é o cliente de backend do serviço (Bearer =
GitHub PAT). Por isso NÃO há `MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN` genéricos:
o cliente já é específico do GitHub/ACR.

Prefixo das vars do serviço: DEPLOY_ (ex.: DEPLOY_GITHUB_TOKEN). As vars de
integração com o gateway (MCP_TWIN_AUDIENCE, URL_ADMIN_TWIN_JWKS, MCP_PORT,
DOCS_ENABLED, MCP_SERVICE_LOG_LEVEL) usam o nome EXATO via validation_alias
(o alias tem precedência sobre o env_prefix).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from pathlib import Path

# namespace canônico = name_microservice ('platform-deploy-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "deploy-mcp"


class DeploySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEPLOY_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401). validation_alias tem precedência sobre
    # env_prefix, então lê MCP_TWIN_AUDIENCE (não DEPLOY_MCP_TWIN_AUDIENCE).
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── GitHub (backend do serviço) ─────────────────────────────────────────── #
    github_token: str = Field(description="GitHub PAT com escopos repo + workflow (obrigatório).")
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

    def get_repos_root_path(self) -> Path | None:
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
