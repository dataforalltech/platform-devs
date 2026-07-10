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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-config-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "config-mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

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
    # Chave Fernet para encriptar/decriptar valores no store. Vazia → build_server
    # aborta (fail-fast) na validação do encryptor.
    master_key: str = Field(default="", validation_alias="CONFIG_MCP_MASTER_KEY")


# Alias retrocompatível — código/deploy antigo referenciava ConfigMcpSettings.
ConfigMcpSettings = Settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
