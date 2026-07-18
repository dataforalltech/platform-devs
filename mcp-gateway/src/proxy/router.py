"""Manifest-driven, fail-closed proxy routes for MCP providers."""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from src.auth.policy import PolicyUnavailable, policy_client
from src.auth.token_exchange import TokenExchangeUnavailable, exchange_token
from src.auth.token_validator import UserSession, authenticate_request
from src.middleware.audit_logger import AuditUnavailable, assert_audit_available, log_tool_call
from src.middleware.rate_limiter import check_rate_limit
from src.registry import Provider, RegistryUnavailable, runtime_registry
from src.security.context import (
    ContextConfigurationError,
    ExecutionContext,
    build_context,
    sign_context,
)

_FORBIDDEN_ARGUMENTS = {
    "_meta",
    "tenant_id",
    "approved",
    "human_approved",
    "approval",
    "approval_ids",
    "password",
    "secret",
    "private_key",
    "private_key_pem",
    "access_token",
    "refresh_token",
    "credential",
}


def _forbidden_argument_name(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    compact = normalized.replace("_", "")
    return normalized in _FORBIDDEN_ARGUMENTS or any(
        marker in compact
        for marker in (
            "clientsecret",
            "apikey",
            "privatekey",
            "accesstoken",
            "refreshtoken",
        )
    )


async def _get_user_or_fail(authorization: str | None) -> UserSession:
    user = await authenticate_request(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not user.tenant_id:
        raise HTTPException(status_code=403, detail="Verified tenant context is required")
    return user


def _provider_or_fail(name: str) -> Provider:
    try:
        provider = runtime_registry.get(name)
    except RegistryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if provider is None:
        raise HTTPException(status_code=404, detail="MCP provider not found")
    return provider


def _argument_keys(value: Any, *, depth: int = 0) -> set[str]:
    if depth > 8:
        raise HTTPException(status_code=400, detail="arguments exceed maximum nesting depth")
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for item in value.values():
            keys.update(_argument_keys(item, depth=depth + 1))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value[:1000]:
            keys.update(_argument_keys(item, depth=depth + 1))
        return keys
    return set()


def _validate_arguments(tool: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=400, detail="arguments must be an object")
    argument_keys = _argument_keys(arguments)
    forbidden = {key for key in argument_keys if _forbidden_argument_name(key)}
    if "value" in argument_keys and (
        "credential" in tool.lower() or "secret" in tool.lower()
    ):
        forbidden.add("value")
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail=f"untrusted context or secret-bearing arguments are forbidden: {sorted(forbidden)}",
        )
    return arguments


def _requested_approvals(header: str | None) -> list[str]:
    if not header:
        return []
    return sorted({item.strip() for item in header.split(",") if item.strip()})


def _validate_contract_input(
    arguments: dict[str, Any], local_policy: dict[str, Any] | None
) -> None:
    if not local_policy or not isinstance(local_policy.get("input_schema"), dict):
        return
    try:
        Draft202012Validator(local_policy["input_schema"]).validate(arguments)
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path) or "arguments"
        raise HTTPException(
            status_code=400,
            detail=f"arguments violate canonical tool contract at {path}",
        ) from exc
    except SchemaError as exc:
        raise HTTPException(
            status_code=503, detail="canonical tool contract is invalid"
        ) from exc


def _audit_payload(
    *,
    context: ExecutionContext,
    provider: str,
    tool: str,
    arguments: dict[str, Any],
    result: Any,
    status: str,
    duration_ms: int,
    request: Request,
) -> dict[str, Any]:
    payload = context.payload()
    payload.update(
        {
            "mcp": provider,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "duration_ms": duration_ms,
            "status": status,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent", ""),
        }
    )
    return payload


def _filter_disabled_tools(payload: dict[str, Any], provider: Provider) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        return payload
    disabled = {
        name for name, policy in provider.tool_policies.items() if policy.get("status") == "disabled"
    }
    result["tools"] = [tool for tool in result["tools"] if tool.get("name") not in disabled]
    return payload


def setup_proxy_routes(app: FastAPI) -> None:
    @app.get("/mcp")
    async def list_mcps(authorization: str | None = Header(None)) -> dict[str, Any]:
        await _get_user_or_fail(authorization)
        try:
            providers = runtime_registry.list()
        except RegistryUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "mcps": [
                {"name": provider.name, "status": "configured"} for provider in providers
            ]
        }

    @app.get("/mcp/{mcp_name}/tools")
    async def list_tools(
        mcp_name: str,
        authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        await _get_user_or_fail(authorization)
        provider = _provider_or_fail(mcp_name)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{provider.url}{provider.tools_list_path}")
                response.raise_for_status()
                return _filter_disabled_tools(response.json(), provider)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="provider tools unavailable") from exc

    @app.post("/mcp/{mcp_name}/tools/call")
    async def call_tool(
        mcp_name: str,
        http_request: Request,
        request: dict[str, Any],
        authorization: str | None = Header(None),
        x_correlation_id: str | None = Header(None),
        x_causation_id: str | None = Header(None),
        x_session_id: str | None = Header(None),
        x_approval_ids: str | None = Header(None),
    ) -> Any:
        started = time.monotonic()
        user = await _get_user_or_fail(authorization)
        provider = _provider_or_fail(mcp_name)
        tool_name = request.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise HTTPException(status_code=400, detail="Missing tool name")
        arguments = _validate_arguments(tool_name, request.get("arguments", {}))
        context = build_context(
            user,
            correlation_id=x_correlation_id,
            causation_id=x_causation_id,
            session_id=x_session_id,
        )
        local_policy = provider.tool_policies.get(tool_name)
        _validate_contract_input(arguments, local_policy)

        try:
            await assert_audit_available()
        except AuditUnavailable as exc:
            raise HTTPException(status_code=503, detail="activity ledger unavailable") from exc

        if local_policy and local_policy.get("status") == "disabled":
            await log_tool_call(
                **_audit_payload(
                    context=context,
                    provider=mcp_name,
                    tool=tool_name,
                    arguments=arguments,
                    result={"error": "tool_disabled"},
                    status="disabled",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    request=http_request,
                )
            )
            raise HTTPException(status_code=403, detail="tool disabled by canonical contract")

        try:
            await check_rate_limit(user.user_id, user.role)
            decision = await policy_client.authorize(
                context=context,
                provider=mcp_name,
                tool=tool_name,
                arguments=arguments,
                requested_approval_ids=_requested_approvals(x_approval_ids),
                local_policy=local_policy,
            )
        except HTTPException:
            raise
        except (PolicyUnavailable, ConnectionError) as exc:
            raise HTTPException(status_code=503, detail="authorization policy unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="rate limit dependency unavailable") from exc

        governed_context = context.with_policy(decision.decision_id, decision.approval_ids)
        if not decision.allowed:
            await log_tool_call(
                **_audit_payload(
                    context=governed_context,
                    provider=mcp_name,
                    tool=tool_name,
                    arguments=arguments,
                    result={"error": "policy_denied", "reason": decision.reason},
                    status="denied",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    request=http_request,
                )
            )
            raise HTTPException(status_code=403, detail="policy denied")
        if local_policy and local_policy.get("risk", {}).get("approval_required") != "none":
            if not decision.approval_ids:
                raise HTTPException(status_code=403, detail="verified approval required")

        try:
            encoded_context, context_signature = sign_context(governed_context)
            inner_token = await exchange_token(authorization or "", mcp_name)
        except (ContextConfigurationError, TokenExchangeUnavailable) as exc:
            raise HTTPException(status_code=503, detail="trusted downstream context unavailable") from exc

        # Authorization and ledger availability are proven before any downstream side effect.
        await log_tool_call(
            **_audit_payload(
                context=governed_context,
                provider=mcp_name,
                tool=tool_name,
                arguments=arguments,
                result={"decision": "authorized"},
                status="authorized",
                duration_ms=int((time.monotonic() - started) * 1000),
                request=http_request,
            )
        )
        downstream = {
            "jsonrpc": "2.0",
            "id": request.get("id", 1),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
                "_meta": {
                    "twin_token": inner_token,
                    "signed_context": encoded_context,
                    "context_signature": context_signature,
                    "policy_decision_id": decision.decision_id,
                    "approval_ids": decision.approval_ids,
                },
            },
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{provider.url}{provider.tools_call_path}",
                    json=downstream,
                    headers={
                        "X-MCP-Context": encoded_context,
                        "X-MCP-Context-Signature": context_signature,
                    },
                )
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            await log_tool_call(
                **_audit_payload(
                    context=governed_context,
                    provider=mcp_name,
                    tool=tool_name,
                    arguments=arguments,
                    result={"error": "provider_call_failed"},
                    status="error",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    request=http_request,
                )
            )
            raise HTTPException(status_code=503, detail="provider call failed") from exc

        await log_tool_call(
            **_audit_payload(
                context=governed_context,
                provider=mcp_name,
                tool=tool_name,
                arguments=arguments,
                result=result,
                status="success",
                duration_ms=int((time.monotonic() - started) * 1000),
                request=http_request,
            )
        )
        return result
