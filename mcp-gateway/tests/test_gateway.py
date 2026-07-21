from __future__ import annotations

import json

import bcrypt
import pytest
from fastapi.testclient import TestClient

from src.auth.policy import PolicyUnavailable
from src.auth.token_validator import UserSession, authenticate_request
from src.main import app, validate_configuration
from src.middleware.audit_logger import redact
from src.proxy import router
from src.registry import Provider, RegistryUnavailable, RuntimeRegistry
from src.security.context import ContextConfigurationError, build_context, sign_context


def _static_token(raw: str, *, tenant_id: str) -> str:
    return json.dumps(
        [
            {
                "token_hash": bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode(),
                "user_id": "actor-1",
                "actor_type": "agent",
                "role": "developer",
                "scopes": ["mcp:call"],
                "tenant_id": tenant_id,
            }
        ]
    )


@pytest.mark.asyncio
async def test_static_token_requires_verified_tenant(monkeypatch) -> None:
    monkeypatch.setenv(
        "GATEWAY_STATIC_TOKENS_JSON", _static_token("token", tenant_id="")
    )
    assert await authenticate_request("Bearer token") is None


def test_recursive_redaction_never_persists_secret_material() -> None:
    payload = {
        "authorization": "Bearer secret",
        "nested": {"private_key_pem": "PEM", "safe": "ok"},
        "items": [{"password": "p"}],
    }
    assert redact(payload) == {
        "authorization": "<redacted>",
        "nested": {"private_key_pem": "<redacted>", "safe": "ok"},
        "items": [{"password": "<redacted>"}],
    }


def test_context_signing_is_required_and_tenant_bound(monkeypatch) -> None:
    user = UserSession("actor", "developer", ["mcp:call"], "tenant-a", "agent")
    context = build_context(
        user, correlation_id="corr", causation_id="cause", session_id="session"
    ).with_policy("decision-1", ["approval-1"])
    monkeypatch.delenv("GATEWAY_CONTEXT_SIGNING_KEY", raising=False)
    with pytest.raises(ContextConfigurationError):
        sign_context(context)
    monkeypatch.setenv("GATEWAY_CONTEXT_SIGNING_KEY", "test-signing-key")
    encoded, signature = sign_context(context)
    assert encoded and signature
    assert context.payload()["tenant_id"] == "tenant-a"


def test_runtime_registry_fails_when_an_active_provider_has_no_url(tmp_path) -> None:
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(
        json.dumps(
            {
                "services": {
                    "external-mcp": {
                        "gateway_enabled": True,
                        "url_env": "MISSING_PROVIDER_URL",
                        "transport": {"canonical_http": {}},
                        "security": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegistryUnavailable, match="no configured runtime URL"):
        RuntimeRegistry(registry_file).list()


def test_remote_url_overrides_local_registry_url(tmp_path, monkeypatch) -> None:
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(
        json.dumps(
            {
                "services": {
                    "hybrid-mcp": {
                        "gateway_enabled": True,
                        "url": "http://hybrid-mcp:7000",
                        "url_env": "HYBRID_MCP_URL",
                        "transport": {"canonical_http": {}},
                        "security": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry = RuntimeRegistry(registry_file)
    assert registry.get("hybrid-mcp").url == "http://hybrid-mcp:7000"
    monkeypatch.setenv("HYBRID_MCP_URL", "https://remote.example.test/mcp/")
    assert registry.get("hybrid-mcp").url == "https://remote.example.test/mcp"


def test_gateway_configuration_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("GATEWAY_PDP_URL", raising=False)
    with pytest.raises(RuntimeError, match="GATEWAY_PDP_URL"):
        validate_configuration()


def _provider(*, disabled: bool = False) -> Provider:
    return Provider(
        name="devteam-mcp",
        url="http://devteam-mcp:7100",
        transport={
            "canonical_http": {
                "tools_list": "/mcp/tools/list",
                "tools_call": "/mcp/tools/call",
            }
        },
        security={},
        tool_policies={
            "infra_get_lease_ssh_key": {
                "status": "disabled" if disabled else "active",
                "risk": {"approval_required": "N2"},
                "output_schema": {"type": "object"},
            }
        },
    )


def _patch_request_dependencies(monkeypatch, *, provider: Provider) -> None:
    async def user(_authorization):
        return UserSession("actor", "developer", ["mcp:call"], "tenant-a", "agent")

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(router, "authenticate_request", user)
    monkeypatch.setattr(router.runtime_registry, "get", lambda _name: provider)
    monkeypatch.setattr(router, "assert_audit_available", noop)
    monkeypatch.setattr(router, "log_tool_call", noop)
    monkeypatch.setattr(router, "check_rate_limit", noop)


def test_disabled_tool_is_blocked_before_downstream(monkeypatch) -> None:
    _patch_request_dependencies(monkeypatch, provider=_provider(disabled=True))
    response = TestClient(app).post(
        "/mcp/devteam-mcp/tools/call",
        json={"name": "infra_get_lease_ssh_key", "arguments": {"lease_id": "l-1"}},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "tool disabled by canonical contract"


def test_caller_cannot_self_assert_approval(monkeypatch) -> None:
    _patch_request_dependencies(monkeypatch, provider=_provider())
    response = TestClient(app).post(
        "/mcp/devteam-mcp/tools/call",
        json={"name": "infra_request_vm", "arguments": {"human_approved": True}},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 400
    assert "human_approved" in response.json()["detail"]


def test_nested_secret_bearing_arguments_are_rejected(monkeypatch) -> None:
    _patch_request_dependencies(monkeypatch, provider=_provider())
    response = TestClient(app).post(
        "/mcp/devteam-mcp/tools/call",
        json={
            "name": "config_set_workspace_config",
            "arguments": {"body": {"nested": {"password": "do-not-forward"}}},
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 400
    assert "password" in response.json()["detail"]


def test_unavailable_policy_denies_execution(monkeypatch) -> None:
    _patch_request_dependencies(monkeypatch, provider=_provider())

    async def unavailable(**_kwargs):
        raise PolicyUnavailable("offline")

    monkeypatch.setattr(router.policy_client, "authorize", unavailable)
    response = TestClient(app).post(
        "/mcp/devteam-mcp/tools/call",
        json={"name": "infra_get_lease_ssh_key", "arguments": {"lease_id": "lease-1"}},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "authorization policy unavailable"


def test_tools_list_uses_signed_context_and_inner_token(monkeypatch) -> None:
    _patch_request_dependencies(monkeypatch, provider=_provider())
    monkeypatch.setenv("GATEWAY_CONTEXT_SIGNING_KEY", "test-signing-key")
    observed = {}

    async def token_exchange(_authorization, _audience):
        return "exchanged-token"

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jsonrpc": "2.0", "result": {"tools": []}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            observed.update({"url": url, "headers": headers})
            return Response()

    monkeypatch.setattr(router, "exchange_token", token_exchange)
    monkeypatch.setattr(router.httpx, "AsyncClient", Client)
    response = TestClient(app).get(
        "/mcp/devteam-mcp/tools", headers={"Authorization": "Bearer test"}
    )
    assert response.status_code == 200
    assert observed["headers"]["X-MCP-Inner-Token"] == "exchanged-token"
    assert observed["headers"]["X-MCP-Context"]
    assert observed["headers"]["X-MCP-Context-Signature"]


def test_uncontracted_tool_is_rejected_before_policy_or_provider(monkeypatch) -> None:
    _patch_request_dependencies(monkeypatch, provider=_provider())
    response = TestClient(app).post(
        "/mcp/devteam-mcp/tools/call",
        json={"name": "uncontracted_tool", "arguments": {}},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "tool is absent from the canonical contract catalog"
    )


def test_provider_output_must_match_canonical_contract() -> None:
    policy = {
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["observed"],
            "properties": {"observed": {"type": "boolean"}},
        }
    }
    router._validate_contract_output(
        {"jsonrpc": "2.0", "id": 1, "result": {"observed": True}}, policy
    )
    with pytest.raises(Exception, match="provider result violates canonical contract"):
        router._validate_contract_output(
            {"jsonrpc": "2.0", "id": 1, "result": {"observed": "yes"}}, policy
        )


def test_tool_discovery_hides_tools_without_active_contract() -> None:
    payload = {
        "jsonrpc": "2.0",
        "result": {"tools": [{"name": "infra_get_lease_ssh_key"}, {"name": "unknown"}]},
    }
    filtered = router._filter_disabled_tools(payload, _provider())
    assert filtered["result"]["tools"] == [{"name": "infra_get_lease_ssh_key"}]
