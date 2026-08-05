"""Settings do deploy-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`deploy-mcp` é COMPUTE + STATEFUL: fala com um BACKEND (GitHub REST API + ACR) via o
`GitHubClient` (src/knowledge/github_client.py) — cliente de backend do serviço
(Bearer = GitHub PAT) — E persiste um LEDGER das operações num MySQL/PostgreSQL
tenant-scoped (ORM canônico, dual-db, credencial-zero, ORM-H-12). Por isso NÃO há
`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN` genéricos (o cliente já é específico do
GitHub/ACR), MAS há `DBSettings` (DB_*) + `AdminDBSettings` (ADMIN_DB_*) — o mesmo
objeto é passado a `orm.configure()` no boot: a credencial real do banco do tenant
vem de `ADMIN_DATAFORALL.PLATFORMS` (resolvida pela lib a partir do tenant_id).

Prefixo das vars do serviço: DEPLOY_ (ex.: DEPLOY_GITHUB_TOKEN). As vars de
integração com o gateway (MCP_TWIN_AUDIENCE, URL_ADMIN_TWIN_JWKS, MCP_PORT,
DOCS_ENABLED, MCP_SERVICE_LOG_LEVEL) e as do banco (DB_*, ADMIN_DB_*) usam o nome
EXATO via validation_alias (o alias tem precedência sobre o env_prefix).

STD-SEC-004: um único `.env` (discriminador `RUNTIME_ENV`); NENHUM valor com cara
de credencial fica no código — o GitHub PAT, a senha do ACR e as senhas do banco
(DB/admin) vêm de env (ou de Vault via `load_secret`, que tem precedência quando
`VAULT_ADDR` está setado).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

# namespace canônico = name_microservice ('platform-deploy-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "deploy-mcp"


class SecretResolutionError(RuntimeError):
    """Segredo obrigatório não pôde ser resolvido pela fonte aprovada."""


def load_secret(
    name: str,
    fallback: str = "",
    *,
    runtime_env: str = "local",
    required: bool = False,
) -> str:
    """Resolve um segredo pelo bootstrap de segredos do STD-SEC-004.

    Em ``cloud`` a fonte é o Vault e **só** o Vault: qualquer falha de auth/fetch
    levanta ``SecretResolutionError`` e o serviço não sobe — "a ausência ou
    invalidez de uma credencial exigida MUST falhar fechada" (STD-SEC-002, §MUST).
    O ``fallback`` de env/.env é deliberadamente ignorado em cloud, senão o
    bootstrap degrada em silêncio para uma fonte que o standard não admite ali.

    Em ``local`` o Vault é opcional — só é consultado quando ``VAULT_ADDR`` está
    setado — e qualquer falha degrada para o valor de env, que é o "fallback local
    controlado" que o STD-SEC-004 permite.

    ``required`` decide o que fazer com valor AUSENTE (Vault vazio e sem fallback
    utilizável); falha de comunicação em cloud levanta independentemente dele.

    Loga apenas o nome lógico e a FONTE do segredo, nunca o valor (STD-OBS-001).
    """
    is_cloud = runtime_env == "cloud"
    if not is_cloud and not os.getenv("VAULT_ADDR", "").strip():
        _log.debug("secret_source name=%s source=env", name)
        if required and not fallback:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' ausente no runtime local"
            )
        return fallback
    try:
        from platform_crypto import VaultSecretsClient  # lazy: import opcional

        # `service` é o espaço de segredos do serviço (path dataforall/<service>/<name>);
        # `name` é a chave lógica dentro dele. Passar o endereço do Vault aqui — como
        # fazia a versão anterior — monta um path que ninguém provisionou.
        value = VaultSecretsClient(service=NAMESPACE).get(name)
    except Exception as exc:  # noqa: BLE001 — fronteira de bootstrap, mensagem sanitizada
        if is_cloud:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' não pôde ser resolvido do Vault "
                f"({type(exc).__name__})"
            ) from exc
        _log.warning(
            "vault_unavailable name=%s source=env err=%s", name, type(exc).__name__
        )
        if required and not fallback:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' indisponível"
            ) from exc
        return fallback
    if value:
        _log.info("secret_source name=%s source=vault service=%s", name, NAMESPACE)
        return value
    if is_cloud and required:
        raise SecretResolutionError(f"segredo obrigatório '{name}' vazio no Vault")
    if is_cloud:
        _log.warning("secret_empty_from_vault name=%s source=absent", name)
        return ""
    _log.warning("secret_empty_from_vault name=%s source=env", name)
    if required and not fallback:
        raise SecretResolutionError(f"segredo obrigatório '{name}' ausente")
    return fallback


class DeploySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEPLOY_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}. validation_alias absoluto (sem o
    # prefixo DEPLOY_) para casar com o contrato compartilhado dos sidecars.
    runtime_env: str = Field(default="local", validation_alias="RUNTIME_ENV")

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

    # ── Backend do tenant (DBSettings — ORM canônico, dual-db, ledger) ────────
    # Fallback compartilhado (shared-admin credential model): a credencial real do
    # tenant vem de ADMIN_DATAFORALL.PLATFORMS; estes DB_* são o fallback quando a
    # PLATFORMS row não traz o campo. DB_ENGINE decide o dialeto (mysql/postgresql).
    # validation_alias absoluto (sem o prefixo DEPLOY_) — lê DB_HOST, não DEPLOY_DB_HOST.
    DB_ENGINE: str = Field(default="mysql", validation_alias="DB_ENGINE")
    DB_HOST: str = Field(default="", validation_alias="DB_HOST")
    DB_PORT: int = Field(default=3306, validation_alias="DB_PORT")
    DB_NAME: str = Field(default="", validation_alias="DB_NAME")
    DB_USER: str = Field(default="root", validation_alias="DB_USER")
    DB_PASSWORD: str = Field(default="", validation_alias="DB_PASSWORD")
    DB_POOL_MIN_SIZE: int = Field(default=1, validation_alias="DB_POOL_MIN_SIZE")
    DB_POOL_MAX_SIZE: int = Field(default=10, validation_alias="DB_POOL_MAX_SIZE")
    DB_POOL_ACQUIRE_TIMEOUT_SECONDS: float = Field(
        default=30.0, validation_alias="DB_POOL_ACQUIRE_TIMEOUT_SECONDS"
    )
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, validation_alias="DB_POOL_RECYCLE_SECONDS")
    DB_QUERY_TIMEOUT_SECONDS: int = Field(default=60, validation_alias="DB_QUERY_TIMEOUT_SECONDS")
    DB_HEALTH_POOL_SIZE: int = Field(default=1, validation_alias="DB_HEALTH_POOL_SIZE")
    DB_SSLMODE: str | None = Field(default=None, validation_alias="DB_SSLMODE")

    # ── Conexão admin (AdminDBSettings — lê ADMIN_DATAFORALL.PLATFORMS) ────────
    # Resolve o tenant -> credencial do seu banco. É a fonte passada a
    # orm.configure()/get_pool_for_tenant(). O db name é fixo "ADMIN_DATAFORALL".
    ADMIN_DB_HOST: str = Field(default="", validation_alias="ADMIN_DB_HOST")
    ADMIN_DB_PORT: int = Field(default=3306, validation_alias="ADMIN_DB_PORT")
    ADMIN_DB_USER: str = Field(default="root", validation_alias="ADMIN_DB_USER")
    ADMIN_DB_PASSWORD: str = Field(default="", validation_alias="ADMIN_DB_PASSWORD")

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
        description="Nome histórico do template; scaffold de pipeline foi aposentado.",
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

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    @model_validator(mode="after")
    def _resolve_secrets(self) -> DeploySettings:
        """Resolve as credenciais do backend via Vault-fallback (STD-SEC-004).

        O valor de env (``DEPLOY_GITHUB_TOKEN`` / ``DEPLOY_ACR_PASSWORD``) é o
        fallback; o Vault (quando ``VAULT_ADDR`` está setado) tem precedência. Sem
        Vault, o comportamento é idêntico ao de antes (segredo vem do env). Nenhum
        valor com cara de credencial fica no código.
        """
        self.github_token = load_secret("github_token", self.github_token, runtime_env=self.runtime_env)
        # acr_password é opcional (str | None): mantém o None quando nem env nem
        # Vault trazem valor, preservando o contrato "não configurado".
        self.acr_password = load_secret("acr_password", self.acr_password or "", runtime_env=self.runtime_env) or None
        # Senhas do banco (tenant + admin) via Vault-fallback (env se Vault ausente).
        self.DB_PASSWORD = load_secret("db_password", self.DB_PASSWORD, runtime_env=self.runtime_env)
        self.ADMIN_DB_PASSWORD = load_secret("admin_db_password", self.ADMIN_DB_PASSWORD, runtime_env=self.runtime_env)
        return self

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-006). Chamado em build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica).
        - Em cloud, a credencial do backend (GitHub PAT) é obrigatória — deploy-mcp
          opera sobre GitHub/ACR e sem o PAT toda tool falha (STD-SEC-004: o segredo
          vem só do ambiente/Vault, nunca do código; sem default no campo).
        - Em cloud, a conexão admin (host + senha p/ resolver o tenant via PLATFORMS)
          DEVE vir de env/Vault (resolução credencial-zero do banco do tenant).
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud":
            if not self.url_admin_twin_jwks:
                raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")
            if not self.github_token:
                raise RuntimeError("INVARIANTE STD-SEC-004: DEPLOY_GITHUB_TOKEN é obrigatório em cloud")
            if not self.ADMIN_DB_HOST or not self.ADMIN_DB_PASSWORD:
                raise RuntimeError(
                    "INVARIANTE STD-SEC-004: ADMIN_DB_HOST/ADMIN_DB_PASSWORD são obrigatórios em "
                    "cloud (resolução credencial-zero do tenant via PLATFORMS; sem default no código)"
                )

    def get_repos_root_path(self) -> Path | None:
        """Retorna o Path resolvido do repos_root, ou None se nao configurado."""
        from pathlib import Path

        if self.repos_root:
            return Path(self.repos_root).expanduser().resolve()

        # Fallback: variaveis de ambiente comuns
        for env_key in ("REPOS_ROOT", "WORKSPACE_REPOS_ROOT"):
            val = os.environ.get(env_key)
            if val:
                return Path(val).expanduser().resolve()

        return None


@lru_cache(maxsize=1)
def get_settings() -> DeploySettings:
    return DeploySettings()
