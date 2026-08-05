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


def _dotenv_lookup(env_file: object, variable: str) -> str | None:
    """Lê o `.env` configurado para um nome que não tem campo em Settings.

    pydantic-settings carrega o `.env` para dentro dos CAMPOS declarados, nunca
    para dentro de ``os.environ``. A credencial por destino é nomeada em runtime
    e não tem campo, então sem esta leitura o valor do `.env` ficaria invisível —
    enquanto a variável irmã ``INTERNAL_API_TOKEN``, que tem campo, carregaria
    normalmente. Essa assimetria silenciosa é pior que a ausência do fallback.

    Respeita ``env_file`` falsy: é assim que os testes desligam a dependência de
    um `.env` no cwd, e a credencial por destino não pode furar essa proteção.
    """
    if not env_file:
        return None
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover — acompanha pydantic-settings[dotenv]
        return None
    return dotenv_values(str(env_file)).get(variable)


def _parse_internal_targets(raw: str | None) -> list[str]:
    """Normaliza INTERNAL_API_TARGETS em nomes canônicos de destino.

    Recusa nome fora do formato canônico em vez de aceitar e derivar um nome de
    segredo que ninguém provisionou: um destino escrito errado resolveria uma
    entrada inexistente no Vault e só apareceria como 401 no primeiro hop.
    """
    if not raw:
        return []
    targets: list[str] = []
    for chunk in raw.split(","):
        target = chunk.strip()
        if not target:
            continue
        if not _SERVICE_NAME_RE.fullmatch(target):
            raise ValueError(
                f"INTERNAL_API_TARGETS contém '{target}', que não é um nome "
                "canônico de serviço (^[a-z0-9][a-z0-9-]{1,62}$). Use o "
                "metadata.name do service profile do DESTINO — ver "
                "docs/standards/STD-SEC-002-service-to-service.md, seção "
                "'Token de serviço target-bound'."
            )
        if target not in targets:
            targets.append(target)
    return targets


def target_env_var(target: str) -> str:
    """``INTERNAL_API_TOKEN__<DESTINO>`` — nome canônico em maiúsculas, '-' → '_'."""
    return f"INTERNAL_API_TOKEN__{target.replace('-', '_').upper()}"


def target_vault_name(target: str) -> str:
    """``internal_api_token__<destino>`` — nome lógico no Vault, hífens preservados."""
    return f"internal_api_token__{target}"


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
    # Nome canônico do serviço privado que este sidecar chama — o DESTINO, nunca
    # este processo. MUST ser declarado, jamais derivado de APP_NAME por remoção
    # do sufixo "-mcp": é ele que compõe ``internal_api_token__<destino>``, e um
    # nome adivinhado errado resolve uma entrada que ninguém provisionou
    # (STD-SEC-002, §Parâmetros de configuração).
    SERVICE_TARGET_NAME: str = "platform-project-product"
    # Segundo destino do sidecar. Declarado pelo mesmo motivo que o primeiro: o
    # nome entra na credencial, então adivinhá-lo a partir de GOVERNANCE_BASE_URL
    # produziria um nome de segredo que ninguém provisiona.
    GOVERNANCE_TARGET_NAME: str = "platform-governance"
    # CSV dos destinos cuja /api/internal/* este sidecar chama, por nome canônico.
    # Cada destino declarado MUST ter a sua credencial resolvida; destino sem
    # segredo provisionado recusa o boot em QUALQUER ambiente (STD-SEC-002).
    # Vazio ⇒ derivado dos dois nomes acima, que é a topologia real deste sidecar.
    INTERNAL_API_TARGETS: str | None = None
    # Credencial que este sidecar APRESENTA, uma por destino. Preenchido pelo
    # bootstrap; NUNCA lido do ambiente como dict.
    INTERNAL_API_TOKENS: dict[str, str] = Field(default_factory=dict, repr=False)
    # Vista por papel sobre INTERNAL_API_TOKENS, mantida para os clientes já
    # existentes. O valor vem de ``internal_api_token__<SERVICE_TARGET_NAME>``.
    INTERNAL_API_TOKEN: SecretStr | None = None

    MCP_TWIN_AUDIENCE: str
    MCP_TWIN_ISSUER: str
    URL_ADMIN_TWIN_JWKS: str
    IDENTITY_ALLOWED_HOSTS: list[str]

    GOVERNANCE_BASE_URL: str
    GOVERNANCE_ALLOWED_HOSTS: list[str]
    # Idem: vista sobre ``internal_api_token__<GOVERNANCE_TARGET_NAME>``.
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

    @field_validator("SERVICE_TARGET_NAME", "GOVERNANCE_TARGET_NAME")
    @classmethod
    def _validate_target_name(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SERVICE_NAME_RE.fullmatch(value):
            raise ValueError(
                "o nome do destino deve ser o metadata.name canônico do serviço "
                "chamado (^[a-z0-9][a-z0-9-]{1,62}$), em kebab minúsculo — ver "
                "docs/standards/STD-SEC-002-service-to-service.md"
            )
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
        # Passo 1 da "Estratégia de migração" do STD-SEC-002: o destino entra no
        # NOME do segredo. Enquanto o nome for `internal_api_token`, existe um
        # slot só por serviço e o compartilhamento entre destinos não é desvio de
        # operação — é a única configuração possível.
        # Antes de resolver: um destino igual ao próprio sidecar produziria o nome
        # de segredo `internal_api_token__<este-processo>`, e a recusa sairia como
        # "destino sem credencial" — verdadeira, mas escondendo a causa real.
        for campo, valor in (
            ("SERVICE_TARGET_NAME", self.SERVICE_TARGET_NAME),
            ("GOVERNANCE_TARGET_NAME", self.GOVERNANCE_TARGET_NAME),
        ):
            if valor == self.APP_NAME:
                raise ValueError(
                    f"{campo} deve nomear o serviço de DESTINO, não este sidecar "
                    f"({self.APP_NAME}); uma credencial escopada ao próprio "
                    "chamador não está escopada a nada."
                )

        targets = _parse_internal_targets(self.INTERNAL_API_TARGETS) or [
            self.SERVICE_TARGET_NAME,
            self.GOVERNANCE_TARGET_NAME,
        ]
        # Valor pré-carregado pelos campos-vista, usado só como fallback local.
        pre_carregado = {
            self.SERVICE_TARGET_NAME: _secret_text(self.INTERNAL_API_TOKEN),
            self.GOVERNANCE_TARGET_NAME: _secret_text(self.GOVERNANCE_INTERNAL_TOKEN),
        }

        outbound: dict[str, str] = {}
        unresolved: list[str] = []
        for target in targets:
            env_var = target_env_var(target)
            resolved = load_secret(
                target_vault_name(target),
                # `service` é o espaço de segredos do CHAMADOR, não do destino: o
                # valor é "o meu segredo para o destino X", nunca "o segredo do
                # destino X". Quem carrega o destino é o nome, não o espaço.
                service=self.APP_NAME,
                runtime_env=self.RUNTIME_ENV,
                # `required=False` DE PROPÓSITO: com `True`, o load_secret deste
                # sidecar levanta o seu erro genérico ("required local secret X is
                # missing") e a recusa deixa de dizer o que provisionar. A falha
                # fechada não se perde — ela passa a ser o bloco `unresolved`
                # abaixo, que vale em QUALQUER ambiente e nomeia o segredo. Em
                # cloud, falha de comunicação com o Vault continua levantando
                # dentro do próprio load_secret, independentemente deste flag.
                required=False,
                local_value=_dotenv_lookup(self.model_config.get("env_file"), env_var)
                or os.getenv(env_var)
                or pre_carregado.get(target),
            )
            if resolved:
                outbound[target] = resolved
            else:
                unresolved.append(target)

        # Falha fechada em QUALQUER ambiente, não só em cloud: um destino
        # declarado e não provisionado sumiria do dicionário em silêncio, e sumir
        # é pior que faltar — as duas checagens de segredo universal iteram sobre
        # este dicionário, e um destino ausente delas escapa. O boot que mais
        # precisa ser recusado seria o único não inspecionado.
        if unresolved:
            primeiro = unresolved[0]
            raise ValueError(
                "INTERNAL_API_TARGETS declara destino sem credencial resolvida: "
                f"{', '.join(unresolved)}. Provisione "
                f"{target_vault_name(primeiro)} no Vault, ou "
                f"{target_env_var(primeiro)} em env/.env no runtime local. Um "
                "destino declarado e não provisionado falha aqui, e não como 401 "
                "no primeiro hop (ver docs/standards/"
                "STD-SEC-002-service-to-service.md, seção 'Parâmetros de configuração')."
            )
        object.__setattr__(self, "INTERNAL_API_TOKENS", outbound)
        object.__setattr__(
            self, "INTERNAL_API_TOKEN", SecretStr(outbound.get(self.SERVICE_TARGET_NAME, ""))
        )
        object.__setattr__(
            self,
            "GOVERNANCE_INTERNAL_TOKEN",
            SecretStr(outbound.get(self.GOVERNANCE_TARGET_NAME, "")),
        )

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
        if self.SERVICE_TARGET_NAME == self.APP_NAME:
            raise ValueError(
                "SERVICE_TARGET_NAME deve nomear o serviço de DESTINO, não este "
                "sidecar; uma credencial escopada ao próprio chamador não está "
                "escopada a nada."
            )
        if self.GOVERNANCE_TARGET_NAME == self.APP_NAME:
            raise ValueError(
                "GOVERNANCE_TARGET_NAME deve nomear o serviço de DESTINO, não "
                "este sidecar."
            )

        # Passo 1 do STD-SEC-002: extinguir o segredo universal. Estas são as
        # DUAS violações detectáveis de dentro do processo — um valor partilhado
        # entre serviços DIFERENTES continua invisível daqui, e quem o detecta é a
        # revisão do provisionamento no Vault. Nenhuma mensagem cita valor de
        # segredo, só nome de destino.
        _por_valor: dict[str, str] = {}
        for _destino, _valor in sorted(self.INTERNAL_API_TOKENS.items()):
            _primeiro = _por_valor.get(_valor)
            if _primeiro is not None:
                raise ValueError(
                    f"Os destinos '{_primeiro}' e '{_destino}' compartilham a mesma "
                    "credencial de saída. O segredo é POR DESTINO: um valor que "
                    "autentica em dois destinos permite que um deles se passe pelo "
                    "chamador no outro. Provisione "
                    f"{target_vault_name(_primeiro)} e {target_vault_name(_destino)} "
                    "com valores distintos (ver docs/standards/"
                    "STD-SEC-002-service-to-service.md, 'Estratégia de migração', passo 1)."
                )
            _por_valor[_valor] = _destino

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
