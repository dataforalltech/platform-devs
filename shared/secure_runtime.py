"""Canonical, fail-closed HTTP runtime for governed MCP providers.

The gateway is the only trusted caller.  Providers verify the signed execution
context and the audience-bound exchanged inner token (RS256 signature, issuer,
expiry and ``aud == mcp:<service>``) before exposing metadata or executing a
tool.  Arguments and results are validated against JSON Schema at the provider
boundary as a defence in depth measure.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import inspect
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import jwt
from fastapi import FastAPI, Header, HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from jwt import PyJWKClient
from starlette.concurrency import run_in_threadpool

ToolHandler = Callable[[dict[str, Any], "TrustedContext"], Any | Awaitable[Any]]


@dataclass(frozen=True)
class TrustedContext:
    actor_id: str
    actor_type: str
    tenant_id: str
    scopes: frozenset[str]
    environment: str
    correlation_id: str
    policy_decision_id: str | None
    approval_ids: tuple[str, ...]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_scope: str
    mutating: bool
    risk_level: str
    handler: ToolHandler
    approval_required: str = "none"

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "readOnlyHint": not self.mutating,
                "destructiveHint": self.mutating
                and self.risk_level in {"high", "critical"},
                "idempotentHint": not self.mutating,
            },
            "security": {
                "requiredScope": self.required_scope,
                "tenantRequired": True,
                "policyDecisionRequired": True,
                "riskLevel": self.risk_level,
                "approvalRequired": self.approval_required,
            },
        }


class RuntimeConfigurationError(RuntimeError):
    """Raised when a provider cannot verify gateway identity."""


class ToolExecutionError(RuntimeError):
    """Safe, structured business error returned through JSON-RPC."""

    def __init__(
        self,
        error: str,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        code: int = -32000,
    ) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.detail = detail or {}
        self.code = code


def _decode_context(encoded: str, signature: str) -> TrustedContext:
    signing_key = os.environ.get("MCP_CONTEXT_SIGNING_KEY")
    if not signing_key:
        raise RuntimeConfigurationError("MCP_CONTEXT_SIGNING_KEY is required")
    expected = hmac.new(
        signing_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid gateway context signature")
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid gateway context") from exc
    required = ("actor_id", "actor_type", "tenant_id", "correlation_id", "environment")
    if any(
        not isinstance(payload.get(field), str) or not payload[field]
        for field in required
    ):
        raise HTTPException(status_code=401, detail="incomplete gateway context")
    scopes = payload.get("scopes")
    approvals = payload.get("approval_ids", [])
    if not isinstance(scopes, list) or not all(
        isinstance(item, str) for item in scopes
    ):
        raise HTTPException(status_code=401, detail="invalid gateway scopes")
    if not isinstance(approvals, list) or not all(
        isinstance(item, str) for item in approvals
    ):
        raise HTTPException(status_code=401, detail="invalid approval context")
    decision = payload.get("policy_decision_id")
    if decision is not None and (not isinstance(decision, str) or not decision):
        raise HTTPException(status_code=401, detail="invalid policy decision")
    return TrustedContext(
        actor_id=payload["actor_id"],
        actor_type=payload["actor_type"],
        tenant_id=payload["tenant_id"],
        scopes=frozenset(scopes),
        environment=payload["environment"],
        correlation_id=payload["correlation_id"],
        policy_decision_id=decision,
        approval_ids=tuple(approvals),
    )


_jwks_clients: dict[str, PyJWKClient] = {}


def _inner_token_material() -> tuple[str, str | None, str | None]:
    issuer = os.environ.get("MCP_INNER_TOKEN_ISSUER")
    jwks_url = os.environ.get("MCP_INNER_TOKEN_JWKS_URL")
    public_key = os.environ.get("MCP_INNER_TOKEN_PUBLIC_KEY")
    if not issuer or not (jwks_url or public_key):
        raise HTTPException(
            status_code=503, detail="inner token verification is not configured"
        )
    return issuer, jwks_url, public_key


def _verify_inner_token(
    inner_token: str, service_id: str, context: TrustedContext
) -> None:
    """Validate the gateway-exchanged inner token before executing anything.

    Enforces the RS256 signature, issuer, expiry and the provider-bound audience
    ``mcp:<service_id>`` (invariant #6), and rejects a token minted for another
    tenant.  Fail closed when the verification material is absent: a governed
    provider must never run a tool without confirming the credential was minted
    for this provider.
    """
    issuer, jwks_url, public_key = _inner_token_material()
    try:
        if jwks_url:
            client = _jwks_clients.get(jwks_url)
            if client is None:
                client = PyJWKClient(jwks_url)
                _jwks_clients[jwks_url] = client
            key: Any = client.get_signing_key_from_jwt(inner_token).key
        else:
            key = public_key
        claims = jwt.decode(
            inner_token,
            key,
            algorithms=["RS256"],
            audience=f"mcp:{service_id}",
            issuer=issuer,
            leeway=30,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid inner token") from exc
    token_tenant = claims.get("tenant_id")
    if isinstance(token_tenant, str) and token_tenant and token_tenant != context.tenant_id:
        raise HTTPException(status_code=401, detail="inner token tenant mismatch")


def _trusted_request(
    encoded: str | None,
    signature: str | None,
    inner_token: str | None,
    service_id: str,
    *,
    require_policy: bool,
) -> TrustedContext:
    if not encoded or not signature or not inner_token:
        raise HTTPException(
            status_code=401, detail="trusted gateway credentials are required"
        )
    context = _decode_context(encoded, signature)
    _verify_inner_token(inner_token, service_id, context)
    if require_policy and not context.policy_decision_id:
        raise HTTPException(
            status_code=403, detail="verified policy decision is required"
        )
    return context


def _validate(schema: dict[str, Any], value: Any, boundary: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    except SchemaError as exc:
        raise HTTPException(
            status_code=503, detail=f"invalid {boundary} schema"
        ) from exc
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path) or boundary
        status = 400 if boundary == "input" else 500
        raise HTTPException(
            status_code=status, detail=f"{boundary} contract violation at {path}"
        ) from exc


def _jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def create_mcp_app(
    service_id: str,
    definitions: list[ToolDefinition],
    *,
    readiness: Callable[[], None] | None = None,
) -> FastAPI:
    """Create one canonical provider app from explicit tool definitions."""

    tools = {definition.name: definition for definition in definitions}
    if len(tools) != len(definitions):
        raise ValueError("tool names must be unique")
    for definition in definitions:
        Draft202012Validator.check_schema(definition.input_schema)
        Draft202012Validator.check_schema(definition.output_schema)
        if definition.approval_required not in {"none", "N1", "N2"}:
            raise ValueError("approval_required must be none, N1 or N2")
        if (
            definition.risk_level in {"high", "critical"}
            and definition.approval_required == "none"
        ):
            raise ValueError("high/critical tools require an approval level")

    logger = logging.getLogger(f"mcp.runtime.{service_id}")
    app = FastAPI(title=service_id, version="1.0.0")

    @app.get("/v1/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": service_id}

    @app.get("/v1/health/ready")
    async def ready() -> dict[str, str]:
        if not os.environ.get("MCP_CONTEXT_SIGNING_KEY"):
            raise HTTPException(
                status_code=503, detail="runtime signing key unavailable"
            )
        if not os.environ.get("MCP_INNER_TOKEN_ISSUER") or not (
            os.environ.get("MCP_INNER_TOKEN_JWKS_URL")
            or os.environ.get("MCP_INNER_TOKEN_PUBLIC_KEY")
        ):
            raise HTTPException(
                status_code=503, detail="inner token verification is not configured"
            )
        if readiness:
            try:
                readiness()
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="runtime dependency unavailable"
                ) from exc
        return {"status": "ready", "service": service_id}

    @app.get("/mcp/tools/list")
    async def list_tools(
        x_mcp_context: str | None = Header(None),
        x_mcp_context_signature: str | None = Header(None),
        x_mcp_inner_token: str | None = Header(None),
    ) -> dict[str, Any]:
        await run_in_threadpool(
            functools.partial(
                _trusted_request,
                x_mcp_context,
                x_mcp_context_signature,
                x_mcp_inner_token,
                service_id,
                require_policy=False,
            )
        )
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [tool.public_schema() for tool in tools.values()]},
        }

    @app.post("/mcp/tools/call")
    async def call_tool(
        request: dict[str, Any],
        x_mcp_context: str | None = Header(None),
        x_mcp_context_signature: str | None = Header(None),
        x_mcp_inner_token: str | None = Header(None),
    ) -> dict[str, Any]:
        started = time.monotonic()
        context = await run_in_threadpool(
            functools.partial(
                _trusted_request,
                x_mcp_context,
                x_mcp_context_signature,
                x_mcp_inner_token,
                service_id,
                require_policy=True,
            )
        )
        request_id = request.get("id")
        params = request.get("params")
        if (
            request.get("jsonrpc") != "2.0"
            or request.get("method") != "tools/call"
            or not isinstance(params, dict)
        ):
            return _jsonrpc_error(
                request_id, -32600, "invalid JSON-RPC tools/call request"
            )
        name = params.get("name")
        arguments = params.get("arguments", {})
        definition = tools.get(name) if isinstance(name, str) else None
        if definition is None:
            return _jsonrpc_error(request_id, -32601, "tool not found")
        if (
            definition.required_scope not in context.scopes
            and "*" not in context.scopes
        ):
            raise HTTPException(
                status_code=403, detail="required tool scope is missing"
            )
        minimum_approvals = {"none": 0, "N1": 1, "N2": 2}[definition.approval_required]
        if len(set(context.approval_ids)) < minimum_approvals:
            raise HTTPException(
                status_code=403, detail="required tool approval is missing"
            )
        if not isinstance(arguments, dict):
            return _jsonrpc_error(
                request_id, -32602, "tool arguments must be an object"
            )
        _validate(definition.input_schema, arguments, "input")
        status = "error"
        try:
            if inspect.iscoroutinefunction(definition.handler):
                result = await definition.handler(arguments, context)
            else:
                result = await run_in_threadpool(definition.handler, arguments, context)
                if inspect.isawaitable(result):
                    result = await result
            _validate(definition.output_schema, result, "output")
            status = "success"
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ToolExecutionError as exc:
            return _jsonrpc_error(
                request_id,
                exc.code,
                exc.message,
                data={"error": exc.error, "detail": exc.detail},
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "mcp_tool_failed",
                extra={
                    "tool": definition.name,
                    "tenant_id": context.tenant_id,
                    "correlation_id": context.correlation_id,
                },
            )
            return _jsonrpc_error(request_id, -32603, "tool execution failed")
        finally:
            logger.info(
                "mcp_tool_audit",
                extra={
                    "tool": definition.name,
                    "status": status,
                    "actor_id": context.actor_id,
                    "tenant_id": context.tenant_id,
                    "policy_decision_id": context.policy_decision_id,
                    "correlation_id": context.correlation_id,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )

    return app
