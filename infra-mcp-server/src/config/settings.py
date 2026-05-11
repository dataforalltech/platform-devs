"""Configuração do servidor — lida do ambiente, sem hardcode."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do servidor MCP. Defaults seguros — nada é obrigatório."""

    model_config = SettingsConfigDict(
        env_prefix="INFRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    # Configuração do backend remoto como JSON. Exemplos:
    #   S3:     {"bucket":"...", "region":"us-east-1", "dynamodb_table":"tf-locks", "key":"infra-mcp/terraform.tfstate"}
    #   AzureRM: {"resource_group_name":"...", "storage_account_name":"...", "container_name":"tfstate", "key":"infra-mcp.tfstate"}
    #   GCS:    {"bucket":"...", "prefix":"infra-mcp"}
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
    # PostgreSQL connection for allocator store (Phase 2 → PostgreSQL migration)
    pg_host: str = Field(default="claude-dev", description="PostgreSQL host")
    pg_port: int = Field(default=5432, description="PostgreSQL port")
    pg_db: str = Field(default="app", description="PostgreSQL database name")
    pg_user: str = Field(default="postgres", description="PostgreSQL user")
    pg_password: str = Field(default="postgres_password_local_dev", description="PostgreSQL password")
    pg_min_conn: int = Field(default=2, description="Minimum pool connections")
    pg_max_conn: int = Field(default=10, description="Maximum pool connections")

    # SQLite for testing (if INFRA_USE_SQLITE_FOR_TESTING=true, use :memory: for tests)
    use_sqlite_for_testing: bool = Field(default=False, description="Use SQLite :memory: for tests")
    db_path: str = Field(
        default=":memory:",
        description=(
            "Caminho do banco SQLite do allocator (apenas para testes/development). "
            "Default: ':memory:' (testes sem persistência). "
            "Production deve usar PostgreSQL."
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

    log_level: str = Field(default="INFO", description="DEBUG | INFO | WARNING | ERROR")
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

    @property
    def pg_dsn(self) -> str:
        """Return PostgreSQL connection string."""
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
