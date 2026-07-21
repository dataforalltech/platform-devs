"""Servidor MCP do serviço — N tools para <domínio>. GATEWAY-READY (v2.0).

TEMPLATE — reference skeleton. Substitua project_product/portfolio/Portfolio.
Ver docs/_templates/code/README.md. Nos identificadores Python e nomes de tool,
use a forma snake_case de project_product (ex.: catalog_health_check); em títulos/URLs
use a forma kebab-case (ex.: project_product-mcp).

Este sidecar é o kind=mcp_http que o **MCP Gateway central** (platform-mcp-gateway)
agrega. Ele implementa o contrato de integração:
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (contrato normativo)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)
  - docs/it/IT-006-registrar-servico-no-mcp-gateway.md               (passo a passo)
  - docs/_templates/mcp-gateway-integration/                          (registro + rede)

Pontos gateway-ready implementados aqui:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deve depender de
     derivação por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud mcp:<namespace>, ~60s)
     via JWKS do platform-admin (URL_ADMIN_TWIN_JWKS), na sua PRÓPRIA audiência
     (defense in depth — CI-4/CI-5 do STD-MCP-001). Falha de audiência = a falha de
     integração nº 1 (401). O twin token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — NUNCA de argumento/header
     controlável (SEC-035 / INV-3).
  4. Um PolicyEnforcementPoint local roda ANTES do dispatch; o default é deny-all.
     Decisão pending retorna 409 com approvalUid/checkpointUid sem executar.
  5. _EXEMPT_TOOLS (health, sem token) e _EXCLUDE_TOOLS (denylist fail-safe).
  6. O sidecar expõe somente HTTP para o MCP Gateway. Transporte stdio não é
      iniciado nem é uma superfície suportada por este template.
  7. /docs desabilitado em todo ambiente (DOCS_ENABLED=false — HTTP-01).
  8. O receive ASGI limita o corpo antes do parsing; schema local profundo,
     rate limit e PEP rodam antes de qualquer dispatch.
  9. Headers de segurança, request-id sanitizado e logs sem token/body/tenant são
     aplicados a toda resposta HTTP, inclusive erros de limite de corpo.

Config esperada (Settings; segredos via Vault em cloud):
  APP_NAME            = identidade do sidecar usada no path de segredo
  RUNTIME_ENV          = local | cloud
  MCP_TWIN_AUDIENCE   = "mcp:portfolio" (audience canonical das capabilities
                        portfolio.* emitida pelo exchange do platform-admin)
  MCP_TWIN_ISSUER     = issuer explícito do platform-admin
  URL_ADMIN_TWIN_JWKS = URL do JWKS do platform-admin (mesma de STD-SEC-006)
  RATE_LIMIT_STORAGE_URI = Redis compartilhado, obrigatório em cloud e resolvido do Vault
  DOCS_ENABLED        = "false" em todo ambiente
  MCP_PORT            = 7100 (porta do sidecar)

Integração obrigatória:
  build_server(policy=<PEP aprovado>) deve receber o adapter de política do serviço.
  Sem ele, DenyAllPolicyEnforcementPoint mantém todas as tools não exempt em 403.

Streaming (HTTP sidecar):
  GET  /v1/ready         - readiness de API, governance, JWKS e rate limit
  GET  /v1/health        — liveness do processo
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jwt.exceptions import MissingRequiredClaimError

from ..client.api_client import (
    AdapterResponseError,
    AdapterUnavailableError,
    ServiceApiClient,
    TrustedMcpContext,
)
from ..config.settings import Settings, get_settings
from ..schemas import (
    DELETE_PRODUCT_SCHEMA,
    DELETE_PROJECT_SCHEMA,
    DETACH_SCHEMA,
    PRODUCT_CREATE_INPUT,
    PRODUCT_DELETE_INPUT,
    PRODUCT_GET_INPUT,
    PRODUCT_LIST_INPUT,
    PRODUCT_LIST_OUTPUT,
    PRODUCT_SCHEMA,
    PRODUCT_UPDATE_INPUT,
    PROJECT_CREATE_INPUT,
    PROJECT_DELETE_INPUT,
    PROJECT_GET_INPUT,
    PROJECT_LIST_INPUT,
    PROJECT_LIST_OUTPUT,
    PROJECT_SCHEMA,
    PROJECT_UPDATE_INPUT,
    REPOSITORY_ATTACH_INPUT,
    REPOSITORY_BINDING_SCHEMA,
    REPOSITORY_DETACH_INPUT,
    REPOSITORY_LIST_INPUT,
    REPOSITORY_LIST_OUTPUT,
)
from ..tools import (
    InvalidToolResponseError,
    product_create,
    product_delete,
    product_get,
    product_list,
    product_update,
    project_create,
    project_delete,
    project_get,
    project_list,
    project_repository_attach,
    project_repository_detach,
    project_repository_list,
    project_update,
)

_log = logging.getLogger(__name__)

_TENANT_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
_TWIN_USER_SUB_RE = re.compile(r"^(?:user:)?([1-9][0-9]{0,18})$")
_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9._:-]{1,128}$")
_TENANT_GLOBAL_ENVIRONMENT_ID = 0
_MAX_EXECUTION_DEPTH = 5
_MAX_SCHEMA_DEPTH = 16
_MAX_CONCURRENT_JWKS_RESOLUTIONS = 8

_ERROR_MESSAGES = {
    "invalid_request": "The MCP request envelope is invalid.",
    "payload_too_large": "The MCP request body exceeds the configured limit.",
    "unknown_tool": "The requested tool is not available.",
    "tool_excluded": "The requested tool is not exposed for execution.",
    "twin_token_required": "A backend-scoped inner token is required.",
    "twin_token_invalid": "The backend-scoped inner token is invalid.",
    "JTI_REQUIRED": "The inner token must contain a usable jti.",
    "invalid_execution_context": "The execution context is invalid.",
    "invalid_arguments": "Tool arguments failed schema validation.",
    "rate_limited": "The MCP sidecar rate limit was exceeded.",
    "rate_limit_unavailable": "The shared rate-limit control is unavailable.",
    "exec_limit_exceeded": "The maximum execution depth was reached.",
    "policy_unavailable": "The local policy control is unavailable.",
    "policy_denied": "The local policy denied execution.",
    "approval_required": "Human approval is required before execution.",
    "backend_unreachable": "The private service adapter is unreachable.",
    "adapter_server_error": "The private service adapter failed.",
    "adapter_rejected": "The private service adapter rejected the request.",
    "tool_execution_failed": "The tool could not be executed.",
    "invalid_tool_response": "The tool returned an invalid response.",
}


class JtiRequiredError(ValueError):
    """Raised when an inner token does not provide a usable execution-session id."""


class MissingTenantScopeError(ValueError):
    """Raised when a verified inner token has no tenant scope."""


class InvalidTenantScopeError(ValueError):
    """Raised when a verified inner-token tenant scope has an invalid format."""


class InvalidInnerTokenClaimsError(ValueError):
    """Raised when required inner-token claims violate the Model C contract."""


class InvalidExecutionContextError(ValueError):
    """Raised when verified Twin claims cannot form a trusted execution context."""


class InvalidMcpEnvelopeError(ValueError):
    """Raised when the JSON MCP call envelope has an unsupported shape."""


class RequestBodyTooLargeError(RuntimeError):
    """Raised by the ASGI receive guard before FastAPI parses a large body."""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class RateLimitStore(Protocol):
    """Minimal rate-limit backend; cloud implementations must be shared."""

    shared: bool

    async def startup(self) -> None: ...

    async def readiness(self) -> None: ...

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision: ...

    async def close(self) -> None: ...


class InMemoryRateLimitStore:
    """Local-only fixed-window limiter. It is forbidden when RUNTIME_ENV=cloud."""

    shared = False

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        return None

    async def readiness(self) -> None:
        return None

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = int(time.time())
        bucket = now // window_seconds
        async with self._lock:
            stale_before = bucket - 1
            self._counts = {
                item: count for item, count in self._counts.items() if item[1] >= stale_before
            }
            counter_key = (key, bucket)
            count = self._counts.get(counter_key, 0) + 1
            self._counts[counter_key] = count
        retry_after = max(1, window_seconds - (now % window_seconds))
        return RateLimitDecision(count <= limit, retry_after)

    async def close(self) -> None:
        self._counts.clear()


class RedisRateLimitStore:
    """Atomic shared fixed-window limiter using a lazily imported Redis client."""

    shared = True
    _INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

    def __init__(self, settings: Settings) -> None:
        secret_uri = settings.RATE_LIMIT_STORAGE_URI
        if secret_uri is None or not secret_uri.get_secret_value():
            raise RuntimeError("RATE_LIMIT_STORAGE_URI is required for shared rate limiting")
        try:
            import redis.asyncio as redis  # noqa: PLC0415 - optional sidecar dependency
        except ImportError as exc:
            raise RuntimeError(
                "cloud MCP rate limiting requires the approved redis client dependency"
            ) from exc

        timeout = settings.MCP_RATE_LIMIT_CONNECT_TIMEOUT_SECONDS
        self._prefix = settings.MCP_RATE_LIMIT_KEY_PREFIX
        self._client = redis.from_url(
            secret_uri.get_secret_value(),
            decode_responses=False,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
            retry_on_timeout=False,
        )

    async def startup(self) -> None:
        try:
            await self._client.ping()
        except Exception as exc:  # noqa: BLE001 - fail-fast, sanitised
            raise RuntimeError(
                f"shared MCP rate-limit store is unavailable ({type(exc).__name__})"
            ) from exc

    async def readiness(self) -> None:
        try:
            await self._client.ping()
        except Exception as exc:  # noqa: BLE001 - sanitised dependency boundary
            raise RuntimeError(
                f"shared MCP rate-limit store is unavailable ({type(exc).__name__})"
            ) from exc

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        result = await self._client.eval(
            self._INCREMENT_SCRIPT,
            1,
            f"{self._prefix}:{key}",
            window_seconds,
        )
        count = int(result[0])
        retry_after = max(1, int(result[1]))
        return RateLimitDecision(count <= limit, retry_after)

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def _build_rate_limit_store(settings: Settings) -> RateLimitStore:
    if settings.RATE_LIMIT_STORAGE_URI is not None:
        return RedisRateLimitStore(settings)
    if settings.RUNTIME_ENV == "cloud":
        raise RuntimeError("cloud MCP sidecars require a shared rate-limit store")
    return InMemoryRateLimitStore()


def _request_id_from_scope(scope: dict[str, Any]) -> str:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == b"x-request-id":
            try:
                candidate = raw_value.decode("ascii")
            except UnicodeDecodeError:
                break
            if _REQUEST_ID_RE.fullmatch(candidate):
                return candidate
            break
    return uuid.uuid4().hex


def _error_content(
    code: str,
    request_id: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content: dict[str, Any] = {
        "error": code,
        "message": _ERROR_MESSAGES.get(code, "The request could not be completed."),
        "request_id": request_id,
    }
    if details:
        content["details"] = details
    return content


class McpHttpSecurityMiddleware:
    """ASGI guard for body size, response headers, request IDs and safe logs."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        path = str(scope.get("path", ""))
        method = str(scope.get("method", ""))
        started_at = time.monotonic()
        status_code = 500
        response_started = False

        security_headers = {
            b"cache-control": b"no-store",
            b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
            b"referrer-policy": b"no-referrer",
            b"x-content-type-options": b"nosniff",
            b"x-frame-options": b"DENY",
            b"x-request-id": request_id.encode("ascii"),
        }
        if scope.get("scheme") == "https":
            security_headers[b"strict-transport-security"] = b"max-age=31536000"

        def log_completion() -> None:
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            _log.info(
                "mcp_http_request request_id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id,
                method,
                path,
                status_code,
                duration_ms,
            )

        async def secure_send(message: dict[str, Any]) -> None:
            nonlocal status_code, response_started
            if message.get("type") == "http.response.start":
                response_started = True
                status_code = int(message.get("status", 500))
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in security_headers
                ]
                headers.extend(security_headers.items())
                message["headers"] = headers
            await send(message)

        guarded_receive = receive
        if method == "POST" and path == "/mcp/tools/call":
            content_length: int | None = None
            for raw_name, raw_value in scope.get("headers", []):
                if raw_name.lower() == b"content-length":
                    try:
                        content_length = int(raw_value.decode("ascii"))
                    except (UnicodeDecodeError, ValueError):
                        response = JSONResponse(
                            status_code=400,
                            content=_error_content("invalid_request", request_id),
                        )
                        await response(scope, receive, secure_send)
                        log_completion()
                        return
                    break
            if content_length is not None and (
                content_length < 0 or content_length > self.max_body_bytes
            ):
                response = JSONResponse(
                    status_code=413,
                    content=_error_content("payload_too_large", request_id),
                )
                await response(scope, receive, secure_send)
                log_completion()
                return

            received_bytes = 0

            async def limited_receive() -> dict[str, Any]:
                nonlocal received_bytes
                message = await receive()
                if message.get("type") == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > self.max_body_bytes:
                        raise RequestBodyTooLargeError
                return message

            guarded_receive = limited_receive

        try:
            await self.app(scope, guarded_receive, secure_send)
        except RequestBodyTooLargeError:
            if response_started:
                raise
            response = JSONResponse(
                status_code=413,
                content=_error_content("payload_too_large", request_id),
            )
            await response(scope, receive, secure_send)
        finally:
            log_completion()


@dataclass(frozen=True)
class PolicyDecision:
    """Resultado mínimo do PEP local, avaliado antes de qualquer dispatch."""

    outcome: Literal["allow", "deny", "pending"]
    approval_uid: str | None = None
    checkpoint_uid: str | None = None


class PolicyDecisionLike(Protocol):
    @property
    def outcome(self) -> str: ...

    @property
    def approval_uid(self) -> str | None: ...

    @property
    def checkpoint_uid(self) -> str | None: ...


class PolicyEnforcementPoint(Protocol):
    """Adapter obrigatório para a política local do serviço.

    A implementação real deve usar somente identidade/claims já verificados e uma
    política aprovada pelo owner. Indisponibilidade ou erro nunca pode liberar a tool.
    """

    async def evaluate(
        self,
        *,
        tool_name: str,
        metadata: dict[str, Any],
        claims: dict[str, Any],
        arguments: dict[str, Any],
    ) -> PolicyDecisionLike: ...

    async def readiness(self) -> None: ...

    async def aclose(self) -> None: ...


class DenyAllPolicyEnforcementPoint:
    """Default seguro: nenhuma tool de negócio executa sem PEP materializado."""

    async def evaluate(
        self,
        *,
        tool_name: str,
        metadata: dict[str, Any],
        claims: dict[str, Any],
        arguments: dict[str, Any],
    ) -> PolicyDecision:
        del tool_name, metadata, claims, arguments
        return PolicyDecision(outcome="deny")

    async def readiness(self) -> None:
        raise RuntimeError("deny-all policy is not operationally ready")

    async def aclose(self) -> None:
        return None


# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado (para políticas por recurso)
#   data_domain    — domínio de dado (governa HITL floor e classificação LGPD)
# inputSchema MUST ser type=object com properties/required (senão a validação de
# schema no front-door é fail-open).
# ─────────────────────────────────────────────────────────────────────────────

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "product_create": {
        "description": (
            "Create a tenant product using platform-admin user references "
            "without copying user data."
        ),
        "capability": "portfolio.product.create",
        "required_scope": "portfolio:product:write",
        "resource_type": "product",
        "data_domain": "portfolio",
        "schema": PRODUCT_CREATE_INPUT,
        "output_schema": PRODUCT_SCHEMA,
    },
    "product_get": {
        "description": "Get one active tenant product by canonical identifier.",
        "capability": "portfolio.product.get",
        "required_scope": "portfolio:product:read",
        "resource_type": "product",
        "data_domain": "portfolio",
        "schema": PRODUCT_GET_INPUT,
        "output_schema": PRODUCT_SCHEMA,
    },
    "product_list": {
        "description": "List active tenant products with bounded cursor pagination.",
        "capability": "portfolio.product.list",
        "required_scope": "portfolio:product:read",
        "resource_type": "product",
        "data_domain": "portfolio",
        "schema": PRODUCT_LIST_INPUT,
        "output_schema": PRODUCT_LIST_OUTPUT,
    },
    "product_update": {
        "description": "Update a product with idempotency and optimistic concurrency.",
        "capability": "portfolio.product.update",
        "required_scope": "portfolio:product:write",
        "resource_type": "product",
        "data_domain": "portfolio",
        "schema": PRODUCT_UPDATE_INPUT,
        "output_schema": PRODUCT_SCHEMA,
    },
    "product_delete": {
        "description": "Soft-delete an empty product after an approved, version-checked request.",
        "capability": "portfolio.product.delete",
        "required_scope": "portfolio:product:delete",
        "resource_type": "product",
        "data_domain": "portfolio",
        "schema": PRODUCT_DELETE_INPUT,
        "output_schema": DELETE_PRODUCT_SCHEMA,
    },
    "project_create": {
        "description": (
            "Create a project under a product while retaining only opaque "
            "external service references."
        ),
        "capability": "portfolio.project.create",
        "required_scope": "portfolio:project:write",
        "resource_type": "project",
        "data_domain": "portfolio",
        "schema": PROJECT_CREATE_INPUT,
        "output_schema": PROJECT_SCHEMA,
    },
    "project_get": {
        "description": "Get one active tenant project by canonical identifier.",
        "capability": "portfolio.project.get",
        "required_scope": "portfolio:project:read",
        "resource_type": "project",
        "data_domain": "portfolio",
        "schema": PROJECT_GET_INPUT,
        "output_schema": PROJECT_SCHEMA,
    },
    "project_list": {
        "description": "List active tenant projects, optionally filtered by product or status.",
        "capability": "portfolio.project.list",
        "required_scope": "portfolio:project:read",
        "resource_type": "project",
        "data_domain": "portfolio",
        "schema": PROJECT_LIST_INPUT,
        "output_schema": PROJECT_LIST_OUTPUT,
    },
    "project_update": {
        "description": (
            "Update project metadata and external service references with optimistic concurrency."
        ),
        "capability": "portfolio.project.update",
        "required_scope": "portfolio:project:write",
        "resource_type": "project",
        "data_domain": "portfolio",
        "schema": PROJECT_UPDATE_INPUT,
        "output_schema": PROJECT_SCHEMA,
    },
    "project_delete": {
        "description": "Soft-delete a project with no active repository bindings after approval.",
        "capability": "portfolio.project.delete",
        "required_scope": "portfolio:project:delete",
        "resource_type": "project",
        "data_domain": "portfolio",
        "schema": PROJECT_DELETE_INPUT,
        "output_schema": DELETE_PROJECT_SCHEMA,
    },
    "project_repository_attach": {
        "description": (
            "Attach a provider-neutral repository reference resolved by platform-connectors."
        ),
        "capability": "portfolio.repository.attach",
        "required_scope": "portfolio:repository:write",
        "resource_type": "repository_binding",
        "data_domain": "portfolio",
        "schema": REPOSITORY_ATTACH_INPUT,
        "output_schema": REPOSITORY_BINDING_SCHEMA,
    },
    "project_repository_list": {
        "description": "List canonical repository bindings for one tenant project.",
        "capability": "portfolio.repository.list",
        "required_scope": "portfolio:repository:read",
        "resource_type": "repository_binding",
        "data_domain": "portfolio",
        "schema": REPOSITORY_LIST_INPUT,
        "output_schema": REPOSITORY_LIST_OUTPUT,
    },
    "project_repository_detach": {
        "description": "Soft-detach a repository binding after approval and version validation.",
        "capability": "portfolio.repository.detach",
        "required_scope": "portfolio:repository:delete",
        "resource_type": "repository_binding",
        "data_domain": "portfolio",
        "schema": REPOSITORY_DETACH_INPUT,
        "output_schema": DETACH_SCHEMA,
    },
}
# Health/liveness são encaminhadas SEM inner token (CI-9 exempt_tools).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-9 exclude_tools).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Metadados de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _canonical_json(value: Any) -> str | None:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError):
        return None


def _matches_json_format(value: str, format_name: str) -> bool:
    if format_name == "uuid":
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError):
            return False
        return True
    if format_name == "date-time":
        if "T" not in value:
            return False
        normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            return False
        return True
    if format_name == "uri":
        if (
            not value
            or "\\" in value
            or "#" in value
            or any(char.isspace() or ord(char) < 32 for char in value)
        ):
            return False
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return False
        return bool(
            parsed.scheme in {"http", "https"}
            and hostname
            and parsed.username is None
            and parsed.password is None
            and port != 0
        )
    return False


def _validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
    depth: int = 0,
    issues: list[str] | None = None,
) -> list[str]:
    """Validate the security-relevant JSON Schema subset locally.

    Supports the exact subset used by the published tools, including ``anyOf``,
    ``const``, full-match regex patterns, UUID/date-time/safe HTTP(S) URI formats
    and canonical-JSON array uniqueness. Values are never copied into issues.
    """
    if issues is None:
        issues = []
    if len(issues) >= 20:
        return issues
    if depth > _MAX_SCHEMA_DEPTH:
        issues.append(f"{path}: maximum schema depth exceeded")
        return issues

    if "anyOf" in schema:
        any_of = schema["anyOf"]
        if (
            not isinstance(any_of, list)
            or not any_of
            or any(not isinstance(candidate, dict) for candidate in any_of)
        ):
            issues.append(f"{path}: invalid anyOf declaration")
            return issues
        if not any(
            not _validate_json_schema(
                value,
                candidate,
                path=path,
                depth=depth + 1,
                issues=[],
            )
            for candidate in any_of
        ):
            issues.append(f"{path}: value does not match any allowed schema")
            return issues
        schema = {key: item for key, item in schema.items() if key != "anyOf"}

    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else expected
    if expected_types:
        if not isinstance(expected_types, list) or not all(
            isinstance(item, str) for item in expected_types
        ):
            issues.append(f"{path}: invalid schema type declaration")
            return issues
        if not any(_matches_json_type(value, item) for item in expected_types):
            issues.append(f"{path}: type must be {' or '.join(expected_types)}")
            return issues

    if "enum" in schema and value not in schema["enum"]:
        issues.append(f"{path}: value is not in the allowed enum")
        return issues

    if "const" in schema:
        actual = _canonical_json(value)
        expected_const = _canonical_json(schema["const"])
        if actual is None or expected_const is None or actual != expected_const:
            issues.append(f"{path}: value does not match the required constant")
            return issues

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    issues.append(f"{path}.{key}: required property is missing")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            issues.append(f"{path}: invalid schema properties declaration")
            return issues
        extra_keys = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if extra_keys and additional is False:
            issues.append(f"{path}: additional properties are not allowed")
        elif extra_keys and isinstance(additional, dict):
            for key in extra_keys:
                _validate_json_schema(
                    value[key],
                    additional,
                    path=f"{path}.*",
                    depth=depth + 1,
                    issues=issues,
                )
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                _validate_json_schema(
                    value[key],
                    child_schema,
                    path=f"{path}.{key}",
                    depth=depth + 1,
                    issues=issues,
                )
        min_properties = schema.get("minProperties")
        max_properties = schema.get("maxProperties")
        if isinstance(min_properties, int) and len(value) < min_properties:
            issues.append(f"{path}: too few properties")
        if isinstance(max_properties, int) and len(value) > max_properties:
            issues.append(f"{path}: too many properties")

    elif isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            issues.append(f"{path}: too few items")
        if isinstance(max_items, int) and len(value) > max_items:
            issues.append(f"{path}: too many items")
        if schema.get("uniqueItems") is True:
            canonical_items: set[str] = set()
            for item in value:
                canonical = _canonical_json(item)
                if canonical is None:
                    issues.append(f"{path}: array item is not valid JSON")
                    break
                if canonical in canonical_items:
                    issues.append(f"{path}: array items must be unique")
                    break
                canonical_items.add(canonical)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_json_schema(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    issues=issues,
                )

    elif isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            issues.append(f"{path}: string is too short")
        if isinstance(max_length, int) and len(value) > max_length:
            issues.append(f"{path}: string is too long")
        pattern = schema.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                issues.append(f"{path}: invalid schema pattern declaration")
            else:
                try:
                    matches_pattern = re.fullmatch(pattern, value) is not None
                except re.error:
                    issues.append(f"{path}: invalid schema pattern declaration")
                else:
                    if not matches_pattern:
                        issues.append(f"{path}: string does not match the required pattern")
        format_name = schema.get("format")
        if format_name is not None:
            if not isinstance(format_name, str) or not _matches_json_format(value, format_name):
                issues.append(f"{path}: string does not match the required format")

    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            issues.append(f"{path}: number is below minimum")
        if isinstance(maximum, (int, float)) and value > maximum:
            issues.append(f"{path}: number is above maximum")
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            issues.append(f"{path}: number is below exclusive minimum")
        if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
            issues.append(f"{path}: number is above exclusive maximum")

    return issues[:20]


def _parse_call_envelope(body: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not isinstance(body, dict):
        raise InvalidMcpEnvelopeError("body must be an object")
    params = body.get("params", body)
    if not isinstance(params, dict):
        raise InvalidMcpEnvelopeError("params must be an object")
    name = params.get("name")
    if not isinstance(name, str) or not name or len(name) > 128:
        raise InvalidMcpEnvelopeError("name must be a bounded string")
    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise InvalidMcpEnvelopeError("arguments must be an object")
    metadata = params.get("_meta", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise InvalidMcpEnvelopeError("_meta must be an object")
    return name, arguments, metadata


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and _REQUEST_ID_RE.fullmatch(value) else uuid.uuid4().hex


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_error_content(code, _request_id(request), details=details),
        headers=headers,
    )


async def _enforce_rate_limit(
    request: Request,
    *,
    store: RateLimitStore,
    settings: Settings,
    identity: str,
) -> JSONResponse | None:
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    try:
        decision = await store.allow(
            key,
            limit=settings.MCP_RATE_LIMIT_REQUESTS,
            window_seconds=settings.MCP_RATE_LIMIT_WINDOW_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - shared control fails closed
        _log.warning(
            "mcp_rate_limit_unavailable request_id=%s reason=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=503,
            code="rate_limit_unavailable",
        )
    if decision.allowed:
        return None
    return _error_response(
        request,
        status_code=429,
        code="rate_limited",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


async def _verify_inner_token(
    twin_token: str,
    settings: Settings,
    jwks_client: Any,
    resolver_gate: asyncio.Semaphore,
) -> dict[str, Any]:
    """Reverify one Model C inner token against the backend's exact contract.

    The gateway already verified the front token, but the backend is an
    independent verifier.  ``jwks_client`` is constructed once by
    ``build_server`` and reused for every call so key caching and rotation work
    without creating a remote resolver per request.
    """
    header = jwt.get_unverified_header(twin_token)
    if header.get("alg") != "RS256":
        raise InvalidInnerTokenClaimsError("inner token algorithm must be RS256")

    # PyJWKClient performs synchronous HTTP/cache work. Keep it off the event
    # loop and bound concurrent resolutions so an identity outage cannot grow
    # the worker queue without limit. Shielding keeps the gate held until a
    # cancelled worker actually finishes.
    async with resolver_gate:
        resolver_task = asyncio.create_task(
            asyncio.to_thread(jwks_client.get_signing_key_from_jwt, twin_token)
        )
        try:
            signing_key = await asyncio.shield(resolver_task)
        except asyncio.CancelledError:
            await resolver_task
            raise
    claims = jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.MCP_TWIN_AUDIENCE,
        issuer=settings.MCP_TWIN_ISSUER,
        options={
            "require": [
                "exp",
                "iat",
                "iss",
                "aud",
                "jti",
                "parent_jti",
                "sub",
                "tenant_id",
                "scopes",
            ],
            "strict_aud": True,
        },
    )

    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if (
        not isinstance(issued_at, (int, float))
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
    ):
        raise InvalidInnerTokenClaimsError("iat and exp must be numeric dates")
    ttl_seconds = expires_at - issued_at
    if ttl_seconds <= 0 or ttl_seconds > 60:
        raise InvalidInnerTokenClaimsError(
            "inner token TTL must be greater than zero and at most 60 seconds"
        )

    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti.strip() or len(jti) > 256:
        raise JtiRequiredError("inner token has no usable jti")
    for claim_name in ("parent_jti", "sub"):
        claim_value = claims.get(claim_name)
        if not isinstance(claim_value, str) or not claim_value.strip() or len(claim_value) > 256:
            raise InvalidInnerTokenClaimsError(f"inner token has no usable {claim_name}")
    tenant_id = claims.get("tenant_id")
    if not isinstance(tenant_id, str) or not _TENANT_ID_RE.fullmatch(tenant_id):
        raise InvalidTenantScopeError("inner token has an invalid tenant_id claim")
    scopes = claims.get("scopes")
    if not isinstance(scopes, list) or any(
        not isinstance(scope, str) or not scope for scope in scopes
    ):
        raise InvalidInnerTokenClaimsError("inner token scopes must be a string array")
    return claims


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _trusted_context_from_claims(request: Request, claims: dict[str, Any]) -> TrustedMcpContext:
    """Create tenant-global portfolio context from a re-verified inner token.

    Project/product records are shared inside a tenant. ``environment_id=0`` is
    therefore an internal storage scope, not a caller-selectable fallback. The
    platform-mcp gateway does not forward ``X-Environment-Id`` and this sidecar
    deliberately ignores that header.
    """
    tenant_id = claims.get("tenant_id")
    if not isinstance(tenant_id, str) or not _TENANT_ID_RE.fullmatch(tenant_id):
        raise InvalidTenantScopeError("inner token has an invalid tenant_id claim")
    raw_actor_id = claims.get("sub")
    if isinstance(raw_actor_id, bool) or not isinstance(raw_actor_id, (str, int)):
        raise InvalidExecutionContextError("inner token sub must identify a positive user")
    actor_match = _TWIN_USER_SUB_RE.fullmatch(str(raw_actor_id))
    if actor_match is None:
        raise InvalidExecutionContextError("inner token sub must identify a positive user")
    actor_id = int(actor_match.group(1))

    raw_depth = request.headers.get("X-Execution-Depth", "0")
    if len(raw_depth) > 3:
        raise InvalidExecutionContextError("X-Execution-Depth is too long")
    try:
        upstream_depth = int(raw_depth)
    except ValueError as exc:
        raise InvalidExecutionContextError("X-Execution-Depth must be an integer") from exc
    if upstream_depth < 0:
        raise InvalidExecutionContextError("X-Execution-Depth must not be negative")
    if upstream_depth >= _MAX_EXECUTION_DEPTH:
        raise OverflowError("maximum execution depth reached")
    claims["_actor_id"] = actor_id
    claims["_environment_id"] = _TENANT_GLOBAL_ENVIRONMENT_ID
    return TrustedMcpContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        environment_id=_TENANT_GLOBAL_ENVIRONMENT_ID,
        correlation_id=_request_id(request),
        execution_depth=upstream_depth + 1,
    )


def _build_http_app(
    client: ServiceApiClient,
    settings: Settings,
    rate_limit_store: RateLimitStore,
    policy: PolicyEnforcementPoint,
    jwks_client: Any,
    jwks_resolver_gate: asyncio.Semaphore,
) -> FastAPI:
    """Create the hardened HTTP-only sidecar boundary."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await rate_limit_store.startup()
        except Exception:
            await client.aclose()
            raise
        try:
            yield
        finally:
            try:
                await rate_limit_store.close()
            finally:
                close_policy = getattr(policy, "aclose", None)
                if close_policy is not None:
                    await close_policy()
                await client.aclose()

    app = FastAPI(
        title="platform-project-product-mcp",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        McpHttpSecurityMiddleware,
        max_body_bytes=settings.MCP_MAX_REQUEST_BODY_BYTES,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    async def _governance_readiness() -> None:
        probe = getattr(policy, "readiness", None)
        if not callable(probe):
            raise RuntimeError("policy adapter has no readiness probe")
        await probe()

    async def _jwks_readiness() -> None:
        async with jwks_resolver_gate:
            await asyncio.to_thread(jwks_client.get_signing_keys, refresh=True)

    @app.get("/v1/ready")
    async def readiness(request: Request) -> Any:
        checks = {
            "api": client.readiness(),
            "governance": _governance_readiness(),
            "identity_jwks": _jwks_readiness(),
            "rate_limit": rate_limit_store.readiness(),
        }
        results = await asyncio.gather(*checks.values(), return_exceptions=True)
        status_by_dependency = {
            dependency: "ok" if not isinstance(result, BaseException) else "unavailable"
            for dependency, result in zip(checks, results, strict=True)
        }
        unavailable = [
            dependency
            for dependency, dependency_status in status_by_dependency.items()
            if dependency_status != "ok"
        ]
        if unavailable:
            _log.warning(
                "mcp_readiness_failed request_id=%s dependencies=%s",
                _request_id(request),
                ",".join(unavailable),
            )
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "checks": status_by_dependency},
            )
        return {"status": "ready", "checks": status_by_dependency}

    return app


# ── Server ────────────────────────────────────────────────────────────────────


def build_server(
    policy: PolicyEnforcementPoint | None = None,
    *,
    rate_limit_store: RateLimitStore | None = None,
    jwks_client: Any | None = None,
) -> tuple[ServiceApiClient, Settings, FastAPI]:
    """Initialise one HTTP sidecar with singleton security dependencies."""
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    invalid_exempt = [
        name
        for name in _EXEMPT_TOOLS
        if name not in _TOOL_SCHEMAS
        or _TOOL_SCHEMAS[name].get("resource_type") != "health"
        or _TOOL_SCHEMAS[name].get("data_domain") != "operational"
    ]
    if invalid_exempt:
        raise RuntimeError("only operational health tools may be exempt")

    if policy is None:
        from ..governance import GovernancePolicyEnforcementPoint

        policy = GovernancePolicyEnforcementPoint(settings)
    rate_limit_store = rate_limit_store or _build_rate_limit_store(settings)
    if settings.RUNTIME_ENV == "cloud" and not rate_limit_store.shared:
        raise RuntimeError("cloud MCP sidecars require a shared rate-limit store")
    jwks_client = jwks_client or jwt.PyJWKClient(
        settings.URL_ADMIN_TWIN_JWKS,
        timeout=settings.MCP_REQUEST_TIMEOUT_SECONDS,
    )
    jwks_resolver_gate = asyncio.Semaphore(_MAX_CONCURRENT_JWKS_RESOLUTIONS)
    client = ServiceApiClient(settings)
    http_app = _build_http_app(
        client,
        settings,
        rate_limit_store,
        policy,
        jwks_client,
        jwks_resolver_gate,
    )

    _log.info("project_product_mcp_ready tools=%d", len(_TOOL_SCHEMAS))

    @http_app.get("/mcp/tools/list")
    async def http_list_tools(request: Request) -> Any:
        client_host = request.client.host if request.client else "unknown"
        limited = await _enforce_rate_limit(
            request,
            store=rate_limit_store,
            settings=settings,
            identity=f"catalog:{client_host}",
        )
        if limited is not None:
            return limited
        # Emite os metadados de policy junto do contrato MCP (o gateway os lê).
        tools = []
        for name, meta in _TOOL_SCHEMAS.items():
            if name in _EXCLUDE_TOOLS:
                continue
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
                "outputSchema": meta["output_schema"],
            }
            entry.update({f: meta[f] for f in _POLICY_FIELDS})
            tools.append(entry)
        return {"result": {"tools": tools}}

    @http_app.post("/mcp/tools/call")
    async def http_call_tool(request: Request) -> Any:
        try:
            body = await request.json()
            name, arguments, request_metadata = _parse_call_envelope(body)
        except (ValueError, TypeError, InvalidMcpEnvelopeError):
            return _error_response(
                request,
                status_code=400,
                code="invalid_request",
            )

        if name not in _TOOL_SCHEMAS:
            return _error_response(request, status_code=404, code="unknown_tool")

        if name in _EXCLUDE_TOOLS:
            return _error_response(request, status_code=403, code="tool_excluded")

        context: TrustedMcpContext | None = None
        claims: dict[str, Any] = {}
        # Execução não-exempt exige inner token válido; tenant e contexto vêm de
        # claims/header do gateway depois da revalidação, nunca dos argumentos.
        if name not in _EXEMPT_TOOLS:
            twin_token = request_metadata.get("twin_token")
            if not twin_token:
                authorization = request.headers.get("Authorization", "")
                if authorization.startswith("Bearer "):
                    twin_token = authorization.removeprefix("Bearer ").strip()
            if not twin_token:
                return _error_response(
                    request,
                    status_code=401,
                    code="twin_token_required",
                )
            if (
                not isinstance(twin_token, str)
                or len(twin_token.encode("utf-8")) > settings.MCP_MAX_TOKEN_BYTES
            ):
                return _error_response(
                    request,
                    status_code=401,
                    code="twin_token_invalid",
                )
            try:
                claims = await _verify_inner_token(
                    twin_token,
                    settings,
                    jwks_client,
                    jwks_resolver_gate,
                )
                context = _trusted_context_from_claims(request, claims)
            except OverflowError:
                return _error_response(
                    request,
                    status_code=429,
                    code="exec_limit_exceeded",
                )
            except InvalidExecutionContextError:
                return _error_response(
                    request,
                    status_code=400,
                    code="invalid_execution_context",
                )
            except JtiRequiredError:
                return _error_response(
                    request,
                    status_code=401,
                    code="JTI_REQUIRED",
                )
            except MissingRequiredClaimError as exc:
                if exc.claim == "jti":
                    return _error_response(
                        request,
                        status_code=401,
                        code="JTI_REQUIRED",
                    )
                _log.warning(
                    "inner_token_rejected request_id=%s tool=%s reason=%s",
                    _request_id(request),
                    name,
                    type(exc).__name__,
                )
                return _error_response(
                    request,
                    status_code=401,
                    code="twin_token_invalid",
                )
            except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha de verificação
                _log.warning(
                    "inner_token_rejected request_id=%s tool=%s reason=%s",
                    _request_id(request),
                    name,
                    type(exc).__name__,
                )
                return _error_response(
                    request,
                    status_code=401,
                    code="twin_token_invalid",
                )

        schema_issues = _validate_json_schema(arguments, _TOOL_SCHEMAS[name]["schema"])
        if schema_issues:
            return _error_response(
                request,
                status_code=400,
                code="invalid_arguments",
                details={"issues": schema_issues},
            )

        required_scope = _TOOL_SCHEMAS[name]["required_scope"]
        token_scopes = set(claims.get("scopes", []))
        if required_scope not in token_scopes and "*" not in token_scopes:
            return _error_response(request, status_code=403, code="policy_denied")

        # Only true liveness tools may skip policy and rate limiting. Every
        # business tool is limited after token verification and before the PEP.
        if name not in _EXEMPT_TOOLS:
            limited = await _enforce_rate_limit(
                request,
                store=rate_limit_store,
                settings=settings,
                identity=(f"tool:{name}:tenant:{claims['tenant_id']}:sub:{claims['sub']}"),
            )
            if limited is not None:
                return limited

        # O PEP local é obrigatório no Swarm e roda antes do dispatch. O default
        # deny-all impede que um serviço recém-materializado execute tools de
        # negócio antes de integrar e testar sua política real.
        if name not in _EXEMPT_TOOLS:
            try:
                decision = await policy.evaluate(
                    tool_name=name,
                    metadata={field: _TOOL_SCHEMAS[name][field] for field in _POLICY_FIELDS},
                    claims=claims,
                    arguments=arguments,
                )
            except Exception as exc:  # noqa: BLE001 — policy outage é fail-closed
                _log.warning(
                    "policy_evaluation_failed request_id=%s tool=%s reason=%s",
                    _request_id(request),
                    name,
                    type(exc).__name__,
                )
                return _error_response(
                    request,
                    status_code=503,
                    code="policy_unavailable",
                )

            if decision.outcome == "pending":
                if not decision.approval_uid or not decision.checkpoint_uid:
                    _log.error(
                        "invalid_pending_policy_decision request_id=%s tool=%s",
                        _request_id(request),
                        name,
                    )
                    return _error_response(
                        request,
                        status_code=503,
                        code="policy_unavailable",
                    )
                content = _error_content(
                    "approval_required",
                    _request_id(request),
                )
                content["pending"] = {
                    "approvalUid": decision.approval_uid,
                    "checkpointUid": decision.checkpoint_uid,
                }
                return JSONResponse(
                    status_code=409,
                    content=content,
                )
            if decision.outcome != "allow":
                return _error_response(
                    request,
                    status_code=403,
                    code="policy_denied",
                )

        try:
            result = await _dispatch(name, arguments, client, context)
        except AdapterUnavailableError:
            _log.warning(
                "adapter_unreachable request_id=%s tool=%s",
                _request_id(request),
                name,
            )
            return _error_response(
                request,
                status_code=504,
                code="backend_unreachable",
            )
        except AdapterResponseError as exc:
            if exc.status_code >= 500:
                error = "backend_unreachable" if exc.status_code == 504 else "adapter_server_error"
            else:
                error = "adapter_rejected"
            _log.warning(
                "adapter_response_error request_id=%s tool=%s status=%s",
                _request_id(request),
                name,
                exc.status_code,
            )
            return _error_response(
                request,
                status_code=exc.status_code,
                code=error,
            )
        except InvalidToolResponseError:
            _log.error(
                "invalid_tool_response request_id=%s tool=%s source=adapter_contract",
                _request_id(request),
                name,
            )
            return _error_response(
                request,
                status_code=502,
                code="invalid_tool_response",
            )
        except PermissionError:
            return _error_response(
                request,
                status_code=403,
                code="policy_denied",
            )
        except Exception as exc:  # noqa: BLE001 — não vazar detalhes internos ao agente
            _log.error(
                "tool_execution_failed request_id=%s tool=%s type=%s",
                _request_id(request),
                name,
                type(exc).__name__,
            )
            return _error_response(
                request,
                status_code=500,
                code="tool_execution_failed",
            )

        response_issues = _validate_json_schema(result, _TOOL_SCHEMAS[name]["output_schema"])
        if response_issues:
            _log.error(
                "invalid_tool_response request_id=%s tool=%s issues=%s",
                _request_id(request),
                name,
                len(response_issues),
            )
            return _error_response(request, status_code=502, code="invalid_tool_response")

        try:
            result_text = json.dumps(
                result,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            _log.error(
                "invalid_tool_response request_id=%s tool=%s type=%s",
                _request_id(request),
                name,
                type(exc).__name__,
            )
            return _error_response(
                request,
                status_code=502,
                code="invalid_tool_response",
            )

        response_envelope = {"result": {"content": [{"type": "text", "text": result_text}]}}
        encoded_envelope = json.dumps(
            response_envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded_envelope) > settings.MCP_MAX_RESPONSE_BODY_BYTES:
            _log.warning(
                "tool_response_too_large request_id=%s tool=%s",
                _request_id(request),
                name,
            )
            return _error_response(
                request,
                status_code=502,
                code="invalid_tool_response",
            )
        return response_envelope

    return client, settings, http_app


# ── Dispatcher ────────────────────────────────────────────────────────────────
# Adicione um case por tool: if name == "tool_name": return tool_fn(client, **kwargs)
# ─────────────────────────────────────────────────────────────────────────────


async def _dispatch(
    name: str,
    args: dict[str, Any],
    client: ServiceApiClient,
    context: TrustedMcpContext | None,
) -> dict[str, Any]:
    """Dispatch only registered tools with a verified execution context."""
    if context is None:
        raise PermissionError("tool has no verified execution context")
    handlers = {
        "product_create": product_create,
        "product_get": product_get,
        "product_list": product_list,
        "product_update": product_update,
        "product_delete": product_delete,
        "project_create": project_create,
        "project_get": project_get,
        "project_list": project_list,
        "project_update": project_update,
        "project_delete": project_delete,
        "project_repository_attach": project_repository_attach,
        "project_repository_list": project_repository_list,
        "project_repository_detach": project_repository_detach,
    }
    handler = handlers.get(name)
    if handler is None:
        raise KeyError(name)
    result = handler(client, args, context)
    return await result if inspect.isawaitable(result) else result


# Entry point
async def _run() -> None:
    import uvicorn

    _client, _settings, http_app = build_server()

    cfg = uvicorn.Config(
        http_app,
        host="0.0.0.0",  # noqa: S104 — bind interno do container; ingress só via gateway (INV-1)
        port=_settings.MCP_PORT,
        log_level="warning",
        access_log=False,
    )
    server_http = uvicorn.Server(cfg)

    # A integração de produção é exclusivamente mcp_http via platform-mcp-gateway.
    # Não abrir stdio evita um segundo caminho de execução sem o PEP HTTP.
    await server_http.serve()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
