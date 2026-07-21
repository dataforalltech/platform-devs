"""Fail-closed settings for the HTTP-only MCP sidecar.

Cloud resolves secrets exclusively from Vault.  Local development may use the
process environment or the single, gitignored ``.env`` file as a fallback.  The
sidecar never receives an MCP execution credential through these settings:
``INTERNAL_API_TOKEN`` is scoped only to sidecar -> private service adapter.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from platform_crypto import VaultSecretsClient

_log = logging.getLogger(__name__)

_DNS_NAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$"
)
_SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_KEY_PREFIX_RE = re.compile(r"^[a-zA-Z0-9:_-]{1,96}$")
_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "169.254.170.2",
        "100.100.100.200",
        "metadata",
        "metadata.google.internal",
        "metadata.azure.internal",
        "metadata.aws.internal",
    }
)


class SecretResolutionError(RuntimeError):
    """Raised when a required secret cannot be resolved from the approved source."""


def _secret_text(value: SecretStr | str | None) -> str | None:
    if value is None:
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
    return raw if raw else None


@lru_cache(maxsize=8)
def _build_vault_client(service: str) -> VaultSecretsClient:
    """Build one cached Vault client per sidecar identity."""
    from platform_crypto import VaultSecretsClient  # noqa: PLC0415 - lazy by design

    return VaultSecretsClient(service=service)


def load_secret(
    name: str,
    *,
    service: str,
    runtime_env: str,
    local_value: str | None,
    field: str = "value",
    client: VaultSecretsClient | None = None,
    required: bool = True,
) -> str | None:
    """Resolve a secret without allowing an env/.env fallback in cloud.

    ``local_value`` is the value already loaded by Pydantic from the process
    environment or ``.env``.  It is deliberately ignored when
    ``runtime_env == "cloud"``.  Logs contain only the logical secret name and
    source, never the value or Vault exception message.
    """
    if runtime_env not in {"local", "cloud"}:
        raise ValueError("RUNTIME_ENV must be 'local' or 'cloud'")

    use_vault = runtime_env == "cloud" or client is not None or bool(os.getenv("VAULT_ADDR"))
    fallback = None if runtime_env == "cloud" else local_value
    if not use_vault:
        if fallback:
            _log.debug("secret '%s': source=env_or_dotenv (local only)", name)
            return fallback
        if required:
            raise SecretResolutionError(f"required local secret '{name}' is missing")
        return None

    try:
        vault = client or _build_vault_client(service)
        resolved = vault.get(name, field=field)
    except Exception as exc:  # noqa: BLE001 - sanitised bootstrap boundary
        if runtime_env == "cloud":
            raise SecretResolutionError(
                f"required cloud secret '{name}' could not be resolved from Vault "
                f"({type(exc).__name__})"
            ) from exc
        if fallback:
            _log.warning(
                "secret '%s': Vault unavailable (%s); source=env_or_dotenv (local only)",
                name,
                type(exc).__name__,
            )
            return fallback
        if required:
            raise SecretResolutionError(f"required local secret '{name}' is unavailable") from exc
        return None

    resolved_text = _secret_text(resolved)
    if resolved_text:
        _log.info("secret '%s': source=vault service=%s", name, service)
        return resolved_text
    if fallback:
        _log.warning("secret '%s': Vault empty; source=env_or_dotenv (local only)", name)
        return fallback
    if required:
        boundary = "cloud" if runtime_env == "cloud" else "local"
        raise SecretResolutionError(f"required {boundary} secret '{name}' is missing in Vault")
    return None


def _normalise_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if not host or any(char in host for char in ("/", "?", "#", "@", "%", "*")):
        raise ValueError("host allowlists accept only exact hostnames or IP addresses")
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        if not _DNS_NAME_RE.fullmatch(host):
            raise ValueError("invalid hostname in allowlist") from None
        return host


def _validate_destination_host(host: str, *, runtime_env: str) -> str:
    normalised = _normalise_host(host)
    if normalised in _METADATA_HOSTS:
        raise ValueError("metadata endpoints are forbidden")
    try:
        address = ipaddress.ip_address(normalised)
    except ValueError:
        return normalised
    if (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise ValueError("link-local, metadata, multicast and reserved destinations are forbidden")
    if runtime_env == "cloud" and address.is_loopback:
        raise ValueError("loopback destinations are forbidden in cloud")
    return normalised


def _parse_url(value: str, *, allow_path: bool) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use an explicit http:// or https:// scheme")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL userinfo is forbidden")
    if parsed.query or parsed.fragment:
        raise ValueError("URL query strings and fragments are forbidden")
    if not allow_path and parsed.path not in {"", "/"}:
        raise ValueError("SERVICE_BASE_URL must not contain a path")
    if allow_path and (not parsed.path.startswith("/") or parsed.path == "/"):
        raise ValueError("dependency endpoint URL must contain an explicit path")
    return parsed.scheme, parsed.hostname


def validate_service_base_url(
    value: str,
    *,
    allowed_hosts: list[str],
    runtime_env: str,
    private_network_encrypted: bool,
    tls_verify: bool,
    tls_client_cert_file: str | None,
    tls_client_key_file: str | None,
) -> str:
    """Validate the adapter destination without DNS or network access."""
    scheme, raw_host = _parse_url(value, allow_path=False)
    host = _validate_destination_host(raw_host, runtime_env=runtime_env)
    allowlist = {_normalise_host(item) for item in allowed_hosts}
    if not allowlist or host not in allowlist:
        raise ValueError("SERVICE_BASE_URL host is not present in SERVICE_ALLOWED_HOSTS")
    if runtime_env == "cloud" and scheme == "http" and not private_network_encrypted:
        raise ValueError(
            "cloud HTTP requires PRIVATE_NETWORK_ENCRYPTED=true "
            "and evidence of an encrypted overlay"
        )
    if scheme == "https" and not tls_verify:
        raise ValueError("TLS verification cannot be disabled for SERVICE_BASE_URL")
    if bool(tls_client_cert_file) != bool(tls_client_key_file):
        raise ValueError("SERVICE_TLS_CLIENT_CERT_FILE and SERVICE_TLS_CLIENT_KEY_FILE are a pair")
    if scheme == "http" and (tls_client_cert_file or tls_client_key_file):
        raise ValueError("client certificates require an https:// SERVICE_BASE_URL")
    return value.rstrip("/")


def validate_dependency_endpoint_url(
    value: str,
    *,
    allowed_hosts: list[str],
    runtime_env: str,
    private_network_encrypted: bool,
    tls_verify: bool,
) -> str:
    """Validate a fixed dependency probe endpoint without resolving DNS."""
    scheme, raw_host = _parse_url(value, allow_path=True)
    host = _validate_destination_host(raw_host, runtime_env=runtime_env)
    allowlist = {_normalise_host(item) for item in allowed_hosts}
    if not allowlist or host not in allowlist:
        raise ValueError("dependency endpoint host is not present in its allowlist")
    if runtime_env == "cloud" and scheme == "http" and not private_network_encrypted:
        raise ValueError("cloud HTTP dependency probes require PRIVATE_NETWORK_ENCRYPTED=true")
    if scheme == "https" and not tls_verify:
        raise ValueError("TLS verification cannot be disabled for dependency probes")
    return value


class Settings(BaseSettings):
    """Configuration deliberately limited to the MCP sidecar boundary."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "platform-project-product-mcp"
    RUNTIME_ENV: str = "local"

    SERVICE_BASE_URL: str
    SERVICE_READINESS_URL: str
    SERVICE_ALLOWED_HOSTS: list[str]
    PRIVATE_NETWORK_ENCRYPTED: bool = False
    SERVICE_TLS_VERIFY: bool = True
    SERVICE_TLS_CA_FILE: str | None = None
    SERVICE_TLS_CLIENT_CERT_FILE: str | None = None
    SERVICE_TLS_CLIENT_KEY_FILE: str | None = None
    INTERNAL_API_TOKEN: SecretStr | None = None

    MCP_TWIN_AUDIENCE: str
    MCP_TWIN_ISSUER: str
    URL_ADMIN_TWIN_JWKS: str
    IDENTITY_ALLOWED_HOSTS: list[str]

    GOVERNANCE_BASE_URL: str
    GOVERNANCE_ALLOWED_HOSTS: list[str]
    GOVERNANCE_INTERNAL_TOKEN: SecretStr | None = None

    MCP_PORT: int = Field(default=7100, ge=1, le=65535)
    MCP_REQUEST_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    MCP_MAX_REQUEST_BODY_BYTES: int = Field(default=65_536, ge=1_024, le=1_048_576)
    MCP_MAX_RESPONSE_BODY_BYTES: int = Field(default=262_144, ge=1_024, le=1_048_576)
    MCP_MAX_TOKEN_BYTES: int = Field(default=16_384, ge=1_024, le=65_536)
    MCP_RATE_LIMIT_REQUESTS: int = Field(default=120, ge=1, le=100_000)
    MCP_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1, le=3_600)
    MCP_RATE_LIMIT_KEY_PREFIX: str = "mcp:project_product"
    MCP_RATE_LIMIT_CONNECT_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=10)
    RATE_LIMIT_STORAGE_URI: SecretStr | None = None
    DOCS_ENABLED: bool = False

    @field_validator("APP_NAME")
    @classmethod
    def _validate_app_name(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SERVICE_NAME_RE.fullmatch(value):
            raise ValueError("APP_NAME must be a lower-case kebab service name")
        return value

    @field_validator("RUNTIME_ENV")
    @classmethod
    def _validate_runtime_env(cls, value: str) -> str:
        if value not in {"local", "cloud"}:
            raise ValueError("RUNTIME_ENV must be 'local' or 'cloud'")
        return value

    @field_validator("SERVICE_ALLOWED_HOSTS", "IDENTITY_ALLOWED_HOSTS", "GOVERNANCE_ALLOWED_HOSTS")
    @classmethod
    def _validate_host_allowlist(cls, values: list[str]) -> list[str]:
        normalised = list(dict.fromkeys(_normalise_host(value) for value in values))
        if not normalised:
            raise ValueError("host allowlist must contain at least one exact host")
        return normalised

    @field_validator("MCP_TWIN_AUDIENCE")
    @classmethod
    def _validate_audience(cls, value: str) -> str:
        value = value.strip()
        if value != "mcp:portfolio":
            raise ValueError("MCP_TWIN_AUDIENCE must be mcp:portfolio for portfolio.* capabilities")
        return value

    @field_validator("MCP_TWIN_ISSUER")
    @classmethod
    def _validate_issuer(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 256 or any(char.isspace() for char in value):
            raise ValueError("MCP_TWIN_ISSUER must be an explicit non-empty issuer")
        return value

    @field_validator("MCP_RATE_LIMIT_KEY_PREFIX")
    @classmethod
    def _validate_rate_limit_prefix(cls, value: str) -> str:
        if not _KEY_PREFIX_RE.fullmatch(value):
            raise ValueError("MCP_RATE_LIMIT_KEY_PREFIX contains unsupported characters")
        return value

    @model_validator(mode="after")
    def _hydrate_secrets(self) -> Settings:
        local_token = _secret_text(self.INTERNAL_API_TOKEN)
        token = load_secret(
            "internal_api_token",
            service=self.APP_NAME,
            runtime_env=self.RUNTIME_ENV,
            local_value=local_token,
            required=True,
        )
        object.__setattr__(self, "INTERNAL_API_TOKEN", SecretStr(token or ""))

        governance_token = load_secret(
            "governance_internal_token",
            service=self.APP_NAME,
            runtime_env=self.RUNTIME_ENV,
            local_value=_secret_text(self.GOVERNANCE_INTERNAL_TOKEN),
            required=True,
        )
        object.__setattr__(self, "GOVERNANCE_INTERNAL_TOKEN", SecretStr(governance_token or ""))

        local_rate_uri = _secret_text(self.RATE_LIMIT_STORAGE_URI)
        rate_uri = load_secret(
            "rate_limit_storage_uri",
            service=self.APP_NAME,
            runtime_env=self.RUNTIME_ENV,
            local_value=local_rate_uri,
            required=self.RUNTIME_ENV == "cloud",
        )
        object.__setattr__(
            self,
            "RATE_LIMIT_STORAGE_URI",
            SecretStr(rate_uri) if rate_uri else None,
        )
        return self

    @model_validator(mode="after")
    def _enforce_hardening(self) -> Settings:
        if self.DOCS_ENABLED:
            raise ValueError("DOCS_ENABLED must remain false for the MCP sidecar")
        if not _secret_text(self.INTERNAL_API_TOKEN):
            raise ValueError("INTERNAL_API_TOKEN must be resolved by the approved bootstrap")

        validate_service_base_url(
            self.SERVICE_BASE_URL,
            allowed_hosts=self.SERVICE_ALLOWED_HOSTS,
            runtime_env=self.RUNTIME_ENV,
            private_network_encrypted=self.PRIVATE_NETWORK_ENCRYPTED,
            tls_verify=self.SERVICE_TLS_VERIFY,
            tls_client_cert_file=self.SERVICE_TLS_CLIENT_CERT_FILE,
            tls_client_key_file=self.SERVICE_TLS_CLIENT_KEY_FILE,
        )
        validate_dependency_endpoint_url(
            self.SERVICE_READINESS_URL,
            allowed_hosts=self.SERVICE_ALLOWED_HOSTS,
            runtime_env=self.RUNTIME_ENV,
            private_network_encrypted=self.PRIVATE_NETWORK_ENCRYPTED,
            tls_verify=self.SERVICE_TLS_VERIFY,
        )

        validate_service_base_url(
            self.GOVERNANCE_BASE_URL,
            allowed_hosts=self.GOVERNANCE_ALLOWED_HOSTS,
            runtime_env=self.RUNTIME_ENV,
            private_network_encrypted=self.PRIVATE_NETWORK_ENCRYPTED,
            tls_verify=True,
            tls_client_cert_file=None,
            tls_client_key_file=None,
        )
        if not _secret_text(self.GOVERNANCE_INTERNAL_TOKEN):
            raise ValueError("GOVERNANCE_INTERNAL_TOKEN is required")

        identity_scheme, raw_identity_host = _parse_url(self.URL_ADMIN_TWIN_JWKS, allow_path=True)
        identity_host = _validate_destination_host(raw_identity_host, runtime_env=self.RUNTIME_ENV)
        if identity_host not in set(self.IDENTITY_ALLOWED_HOSTS):
            raise ValueError("URL_ADMIN_TWIN_JWKS host is not present in IDENTITY_ALLOWED_HOSTS")
        if (
            self.RUNTIME_ENV == "cloud"
            and identity_scheme == "http"
            and not self.PRIVATE_NETWORK_ENCRYPTED
        ):
            raise ValueError("cloud HTTP JWKS requires the encrypted identity_read overlay")

        rate_uri = _secret_text(self.RATE_LIMIT_STORAGE_URI)
        if self.RUNTIME_ENV == "cloud" and not rate_uri:
            raise ValueError("RATE_LIMIT_STORAGE_URI is required in cloud")
        if rate_uri:
            try:
                rate_scheme = urlsplit(rate_uri).scheme
            except ValueError as exc:
                raise ValueError("RATE_LIMIT_STORAGE_URI is invalid") from exc
            if rate_scheme not in {"redis", "rediss"}:
                raise ValueError("RATE_LIMIT_STORAGE_URI must use redis:// or rediss://")
            if (
                self.RUNTIME_ENV == "cloud"
                and rate_scheme == "redis"
                and not self.PRIVATE_NETWORK_ENCRYPTED
            ):
                raise ValueError(
                    "cloud redis:// requires PRIVATE_NETWORK_ENCRYPTED=true; otherwise use rediss://"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build settings once; secret values are never rendered or logged."""
    return Settings()
