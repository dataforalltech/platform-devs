"""Fail-closed service configuration.

Tenant database endpoints are resolved by platform-database-lib from
ADMIN_DATAFORALL.PLATFORMS. The service never accepts a tenant DSN.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "platform-project-product"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    RUNTIME_ENV: str = "local"
    ROOT_PATH: str = ""
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    HEALTH_PORT: int = Field(default=9090, ge=1, le=65535)
    DOCS_ENABLED: bool = False
    MAX_REQUEST_SIZE_BYTES: int = Field(default=1_048_576, ge=1024)
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)

    PERSISTENCE_ENABLED: bool = True
    DB_ENGINE: str = "postgresql"
    ADMIN_DB_ENGINE: str = "mysql"
    ADMIN_DB_HOST: str
    ADMIN_DB_PORT: int = Field(default=3306, ge=1, le=65535)
    ADMIN_DB_NAME: str = "ADMIN_DATAFORALL"
    ADMIN_DB_USER: str
    ADMIN_DB_PASSWORD: SecretStr | None = None
    DB_POOL_MIN_SIZE: int = Field(default=2, ge=1)
    DB_POOL_MAX_SIZE: int = Field(default=20, ge=2)
    DB_POOL_ACQUIRE_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60)
    DB_QUERY_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=120)
    DB_SSLMODE: str | None = None
    TENANT_POOL_TTL_SECONDS: int = Field(default=300, ge=30)
    READINESS_TENANT_ID: str

    JWT_ALGORITHM: str = "RS256"
    JWT_ISSUER: str
    JWT_AUDIENCE: str
    JWT_JWKS_URL: str
    TENANT_JWT_CLAIM: str = "tenant_id"

    INTERNAL_API_TOKEN: SecretStr | None = None
    METRICS_ENABLED: bool = True
    METRICS_SCRAPE_TOKEN: SecretStr | None = None
    RATE_LIMIT_STORAGE_URI: SecretStr | None = None
    TRUSTED_PROXIES: list[str] = Field(default_factory=list)

    LOG_LEVEL: str = "INFO"
    LOG_TEMP_FOLDER: str = "/tmp/platform-project-product-logs"  # noqa: S108
    OTEL_SERVICE_NAME: str = "platform-project-product"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4318"
    OTEL_TRACES_ENABLED: bool = False
    SENTRY_DSN: str | None = Field(default=None, repr=False)
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("DB_ENGINE", mode="before")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"postgresql", "mysql"}:
            raise ValueError("DB_ENGINE must be postgresql or mysql")
        return normalized

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def validate_algorithm(cls, value: str) -> str:
        if value != "RS256":
            raise ValueError("JWT_ALGORITHM must be RS256")
        return value

    @field_validator("RUNTIME_ENV")
    @classmethod
    def validate_runtime_env(cls, value: str) -> str:
        if value not in {"local", "cloud"}:
            raise ValueError("RUNTIME_ENV must be local or cloud")
        return value

    @model_validator(mode="after")
    def enforce_invariants(self) -> Settings:
        from app.core.secrets import resolve_secret

        self.ADMIN_DB_PASSWORD = resolve_secret(
            "admin_db_password",
            runtime_env=self.RUNTIME_ENV,
            local_value=self.ADMIN_DB_PASSWORD,
        )
        self.INTERNAL_API_TOKEN = resolve_secret(
            "internal_api_token",
            runtime_env=self.RUNTIME_ENV,
            local_value=self.INTERNAL_API_TOKEN,
        )
        self.METRICS_SCRAPE_TOKEN = resolve_secret(
            "metrics_scrape_token",
            runtime_env=self.RUNTIME_ENV,
            local_value=self.METRICS_SCRAPE_TOKEN,
            required=self.METRICS_ENABLED,
        )
        self.RATE_LIMIT_STORAGE_URI = resolve_secret(
            "rate_limit_storage_uri",
            runtime_env=self.RUNTIME_ENV,
            local_value=self.RATE_LIMIT_STORAGE_URI,
            required=self.ENVIRONMENT != "test",
        )
        sentry_secret = resolve_secret(
            "sentry_dsn",
            runtime_env=self.RUNTIME_ENV,
            local_value=SecretStr(self.SENTRY_DSN) if self.SENTRY_DSN else None,
            required=False,
        )
        self.SENTRY_DSN = sentry_secret.get_secret_value() if sentry_secret else None

        if not self.PERSISTENCE_ENABLED:
            raise ValueError("platform-project-product is stateful and requires persistence")
        if self.DOCS_ENABLED:
            raise ValueError("DOCS_ENABLED must remain false")
        if "*" in self.CORS_ALLOWED_ORIGINS:
            raise ValueError("wildcard CORS origins are forbidden")
        if self.DB_POOL_MAX_SIZE < self.DB_POOL_MIN_SIZE:
            raise ValueError("DB_POOL_MAX_SIZE must be >= DB_POOL_MIN_SIZE")
        if self.INTERNAL_API_TOKEN is None or not self.INTERNAL_API_TOKEN.get_secret_value():
            raise ValueError("INTERNAL_API_TOKEN is required")
        if self.RUNTIME_ENV == "cloud" and urlsplit(self.JWT_JWKS_URL).scheme != "https":
            raise ValueError("JWT_JWKS_URL must use https in cloud")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
