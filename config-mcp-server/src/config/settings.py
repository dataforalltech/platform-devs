"""Settings do config-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`config-mcp` NÃO é compute-only como o architecture: é uma persona **stateful**
que serve credenciais/ambientes/tenants a partir de um `ConfigStore` encriptado
(arquivo Fernet local). Não há Trinity backend/REST a chamar — o store É o backend
—, então NÃO há `ServiceApiClient`/`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN`. Em vez
disso mantemos `store_path` + `master_key` (a chave Fernet do store em repouso).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-config-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "config-mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # ── Ambiente (STD-SEC-004: um único .env, discriminador RUNTIME_ENV) ───────
    # Não existem .env.dev/.hml/.prod nem ENV_PROFILE; o comportamento por ambiente
    # é gated por RUNTIME_ENV ∈ {local, cloud}.
    runtime_env: str = Field(default="local", validation_alias="RUNTIME_ENV")

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────────
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401).
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── HTTP sidecar ──────────────────────────────────────────────────────────
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")
    log_level: str = Field(default="INFO", validation_alias="MCP_SERVICE_LOG_LEVEL")

    # ── ConfigStore encriptado (estado local; não é backend REST) ─────────────
    store_path: str = Field(
        default="~/.config/dataforalltech/config.enc.json",
        validation_alias="CONFIG_MCP_STORE_PATH",
    )
    # Chave Fernet para encriptar/decriptar valores no store. NUNCA tem default de
    # segredo no código (STD-SEC-004): vazia → build_server aborta (fail-fast) na
    # validação do encryptor. Em cloud é resolvida via Vault (ver resolve_master_key).
    master_key: str = Field(default="", validation_alias="CONFIG_MCP_MASTER_KEY")

    @field_validator("runtime_env")
    @classmethod
    def _validate_runtime_env(cls, v: str) -> str:
        v = (v or "local").strip().lower()
        if v not in ("local", "cloud"):
            raise ValueError("RUNTIME_ENV deve ser 'local' ou 'cloud'")
        return v

    def resolve_master_key(self) -> str:
        """Chave Fernet do store em repouso, preferindo o Vault quando VAULT_ADDR
        está setado (STD-SEC-004). Import lazy + degradação graciosa p/ o valor do
        env (o boot nunca quebra por causa do Vault — ver src/config/secrets.py)."""
        from .secrets import load_secret

        return load_secret("CONFIG_MCP_MASTER_KEY", self.master_key)

    def enforce_security_invariants(self) -> None:
        """Fail-fast no boot (STD-SEC-001 / STD-SEC-004 / STD-SEC-006). Chamado em
        build_server().

        - Swagger/OpenAPI NUNCA exposto (DOCS_ENABLED=false em todo ambiente).
        - Audiência do inner token deve ser exatamente ``mcp:<namespace>``.
        - Em cloud, o JWKS do admin é obrigatório (sem ele o PEP não re-verifica) e a
          master key do store (credencial de backend) DEVE estar resolvida (Vault/env).
        """
        if self.docs_enabled:
            raise RuntimeError("INVARIANTE STD-SEC-001: DOCS_ENABLED deve ser false em todo ambiente")
        if not self.mcp_twin_audience.startswith("mcp:"):
            raise RuntimeError("INVARIANTE STD-SEC-006: MCP_TWIN_AUDIENCE deve ser 'mcp:<namespace>'")
        if self.runtime_env == "cloud":
            if not self.url_admin_twin_jwks:
                raise RuntimeError("INVARIANTE STD-SEC-006: URL_ADMIN_TWIN_JWKS é obrigatório em cloud")
            if not self.resolve_master_key():
                raise RuntimeError("INVARIANTE STD-SEC-004: CONFIG_MCP_MASTER_KEY é obrigatório em cloud")


# Alias retrocompatível — código/deploy antigo referenciava ConfigMcpSettings.
ConfigMcpSettings = Settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
