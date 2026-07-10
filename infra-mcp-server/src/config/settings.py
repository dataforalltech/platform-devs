"""Settings do infra-mcp (sidecar mcp_http, Model C).

Config de integração ao MCP Gateway central conforme:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md

`infra-mcp` NÃO fala com um Trinity backend/REST — as tools operam sobre CLIs
locais (terraform/checkov/infracost) e um allocator SQLite embarcado. Por isso
NÃO há `ServiceApiClient`/`MCP_SERVICE_BASE_URL`/`MCP_SERVICE_TOKEN` (deviação
justificada do esqueleto do template, que assume um backend HTTP).

Os campos de integração com o gateway (mcp_twin_audience, url_admin_twin_jwks,
mcp_port, docs_enabled) usam `validation_alias` — logo lêem as env-vars
canônicas da plataforma (MCP_TWIN_AUDIENCE, URL_ADMIN_TWIN_JWKS, MCP_PORT,
DOCS_ENABLED) SEM o prefixo `INFRA_`. Os demais campos mantêm o prefixo INFRA_.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# namespace canônico = name_microservice ('platform-infra-mcp') menos o prefixo
# 'platform-'. A audiência do inner token DEVE ser exatamente mcp:<namespace>.
NAMESPACE = "infra-mcp"


class Settings(BaseSettings):
    """Configuração do servidor MCP. Defaults seguros — nada é obrigatório."""

    model_config = SettingsConfigDict(
        env_prefix="INFRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Integração com o gateway (STD-MCP-001 / STD-SEC-006) ──────────────── #
    # Audiência exata que o PEP re-verifica no inner token (a falha de integração
    # nº 1 é audiência divergente → 401). validation_alias ⇒ lê MCP_TWIN_AUDIENCE
    # (sem o prefixo INFRA_).
    mcp_twin_audience: str = Field(default=f"mcp:{NAMESPACE}", validation_alias="MCP_TWIN_AUDIENCE")
    # JWKS do platform-admin (emissor do twin/inner token) — mesma de STD-SEC-006.
    url_admin_twin_jwks: str = Field(default="", validation_alias="URL_ADMIN_TWIN_JWKS")

    # ── HTTP sidecar ──────────────────────────────────────────────────────── #
    mcp_port: int = Field(default=7100, validation_alias="MCP_PORT")
    docs_enabled: bool = Field(default=False, validation_alias="DOCS_ENABLED")

    # --------------------------------------------------------------------- #
    # Chaves SSH por VM (Phase 2f)                                         #
    # --------------------------------------------------------------------- #
    # Fernet key (URL-safe base64, 32 bytes) para cifrar as chaves privadas SSH.
    # Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Se ausente, uma chave aleatória é gerada por sessão — chaves SSH são perdidas em restart.
    lease_secret: str | None = Field(
        default=None,
        description=(
            "Fernet key (URL-safe base64, 32 bytes) para cifrar chaves privadas SSH por VM. "
            "Gerado automaticamente por sessão se None — chaves NÃO persistem entre restarts. "
            "Definir INFRA_LEASE_SECRET para persistência."
        ),
    )

    # --------------------------------------------------------------------- #
    # Backend remoto terraform (Phase 2f)                                  #
    # --------------------------------------------------------------------- #
    # Tipo de backend: "local" (default, -state por VM), "s3", "azurerm", "gcs".
    # Com backend remoto: estado isolado por VM via terraform workspaces.
    tf_backend_type: str = Field(
        default="local",
        description=(
            "Tipo de backend terraform para state das VMs: local | s3 | azurerm | gcs. "
            "'local' usa -state=states/<vm_id>.tfstate (Phase 2d comportamento). "
            "Backends remotos usam terraform workspaces com locking nativo."
        ),
    )

    # Configuração do backend remoto como JSON. Exemplos (chaves conforme o backend):
    #   S3:      bucket, region, dynamodb_table, key
    #   AzureRM: resource_group_name, storage_account_name, container_name, key
    #   GCS:     bucket, prefix
    tf_backend_config_json: str | None = Field(
        default=None,
        description=(
            "JSON com configuração do backend remoto terraform. "
            "Obrigatório quando tf_backend_type != 'local'. "
            "Cada chave=valor vira um -backend-config flag no terraform init."
        ),
    )

    # --------------------------------------------------------------------- #
    # Cost cap de provisionamento via infracost (Phase 2g)                #
    # --------------------------------------------------------------------- #
    # Custo mensal máximo em USD para provisionar uma nova VM via TerraformProvisioner.
    # Se None (default), nenhum cap é aplicado. Requer infracost instalado; se binário
    # não encontrado, o cap é ignorado (non-blocking) e a provisão continua.
    cost_cap_usd_month: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Cap de custo mensal em USD para provisão de VM via TerraformProvisioner. "
            "Verificado via 'infracost diff' antes do terraform apply. "
            "None (default) → sem verificação. 0.0 → bloqueia qualquer VM. "
            "Ignorado (warning) se infracost não estiver no PATH."
        ),
    )

    # --------------------------------------------------------------------- #
    # Persistência do allocator — SQLite embarcado (backend OFICIAL, decisão db8902a).
    # A migração bbdda58 (SQLite→PostgreSQL) deixou o store PG como esqueleto
    # não-funcional; o backend atual é SQLite. Migrar para PostgreSQL de verdade
    # (locking por linha para alocação concorrente + testes de integração contra
    # PG real) é um follow-up dedicado — NÃO reintroduzir campos pg_* inertes aqui
    # enquanto o store PostgreSQL não existir de fato.
    db_path: str = Field(
        default=":memory:",
        description=(
            "Caminho do banco SQLite do allocator. Default ':memory:' (testes/dev sem "
            "persistência); defina INFRA_DB_PATH=/data/allocator.db para persistir. "
            "Migração para PostgreSQL: follow-up dedicado."
        ),
    )

    # Diretório de módulos terraform pré-aprovados (Phase 2c+).
    # Cada subdiretório = uma spec (e.g. <root>/cpu-small/main.tf).
    # None → ImmediateProvisioner (mock); configurado → TerraformProvisioner real.
    tf_modules_root: Path | None = Field(
        default=None,
        description=(
            "Raiz dos módulos terraform pré-aprovados para provisionamento de VMs. "
            "None (default) → ImmediateProvisioner (mock). "
            "Definir INFRA_TF_MODULES_ROOT para habilitar TerraformProvisioner."
        ),
    )

    # Timeout para cada operação terraform apply (seconds).
    provision_timeout_sec: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Timeout em segundos para terraform apply (Phase 2c+). Default: 300s (5 min).",
    )

    # Diretório raiz onde os módulos terraform vivem. Default: cwd da chamada.
    terraform_root: Path | None = Field(
        default=None,
        description="Default cwd para terraform CLI. Cada tool aceita override por chamada.",
    )

    # Caminhos de binários — default: descobertos via PATH.
    terraform_bin: str = Field(default="terraform")
    checkov_bin: str = Field(default="checkov")
    tfsec_bin: str = Field(default="tfsec")
    infracost_bin: str = Field(default="infracost")
    az_bin: str = Field(default="az")

    # Timeouts por tipo de operação (segundos).
    plan_timeout: int = Field(default=120, ge=10, le=1800)
    validate_timeout: int = Field(default=30, ge=5, le=300)
    scan_timeout: int = Field(default=180, ge=10, le=900)
    cost_timeout: int = Field(default=60, ge=10, le=600)

    # Truncamento de output para não estourar response do MCP.
    output_max_chars: int = Field(default=16000, ge=1000, le=200000)

    log_level: str = Field(
        default="INFO",
        validation_alias="MCP_SERVICE_LOG_LEVEL",
        description="DEBUG | INFO | WARNING | ERROR",
    )
    log_format: str = Field(default="json", description="json | text")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level deve ser um de {sorted(allowed)}")
        return upper

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, v: str) -> str:
        allowed = {"json", "text"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"log_format deve ser um de {sorted(allowed)}")
        return lower

    @field_validator("terraform_root")
    @classmethod
    def _resolve_terraform_root(cls, v: Path | None) -> Path | None:
        return v.expanduser().resolve() if v is not None else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
