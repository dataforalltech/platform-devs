from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from project_product_mcp.server import mcp_server as server


class RateStore:
    shared = True

    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = 0

    async def startup(self):
        return None

    async def readiness(self):
        return None

    async def close(self):
        return None

    async def allow(self, *_args, **_kwargs):
        self.calls += 1
        return type("Decision", (), {"allowed": self.allowed, "retry_after_seconds": 3})()


@dataclass
class Policy:
    outcome: str = "allow"
    approval_uid: str | None = None
    checkpoint_uid: str | None = None
    calls: int = 0

    async def evaluate(self, **_kwargs):
        self.calls += 1
        return server.PolicyDecision(self.outcome, self.approval_uid, self.checkpoint_uid)

    async def readiness(self):
        return None

    async def aclose(self):
        return None


async def verified(*_args, **_kwargs):
    return {
        "exp": 160,
        "iat": 100,
        "iss": "platform-admin/twin",
        "aud": "mcp:portfolio",
        "jti": "inner-1",
        "parent_jti": "front-1",
        "sub": "user:7",
        "tenant_id": "devteam",
        "scopes": ["portfolio:product:read"],
        "twin_id": "twin-1",
    }


def call_body(arguments=None, token="token"):
    return {
        "params": {
            "name": "product_get",
            "arguments": arguments or {"product_id": "11111111-1111-4111-8111-111111111111"},
            "_meta": {"twin_token": token},
        }
    }


def product_result():
    return {
        "product_id": "11111111-1111-4111-8111-111111111111",
        "slug": "product",
        "name": "Product",
        "description": None,
        "status": "active",
        "owner_user_refs": [],
        "version": 1,
        "created_at": "2026-07-19T00:00:00Z",
        "updated_at": "2026-07-19T00:00:00Z",
        "created_by_ref": "platform-admin:user:7",
        "updated_by_ref": "platform-admin:user:7",
    }


def build(monkeypatch, policy=None, rate=None):
    monkeypatch.setattr(server, "_verify_inner_token", verified)

    async def dispatch(*_args, **_kwargs):
        return product_result()

    monkeypatch.setattr(server, "_dispatch", dispatch)
    return server.build_server(
        policy or Policy(), rate_limit_store=rate or RateStore(), jwks_client=object()
    )[2]


def test_tools_list_exposes_input_output_and_policy_metadata(monkeypatch):
    app = build(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/mcp/tools/list")
    assert response.status_code == 200
    listed = response.json()["result"]["tools"]
    assert len(listed) == 13
    assert all(
        {
            "inputSchema",
            "outputSchema",
            "capability",
            "required_scope",
            "resource_type",
            "data_domain",
        }
        <= item.keys()
        for item in listed
    )


def test_valid_call_orders_auth_scope_policy_and_validated_output(monkeypatch):
    policy = Policy()
    rate = RateStore()
    app = build(monkeypatch, policy, rate)
    with TestClient(app) as client:
        response = client.post("/mcp/tools/call", json=call_body())
    assert response.status_code == 200
    assert policy.calls == 1 and rate.calls >= 1
    assert "Product" in response.json()["result"]["content"][0]["text"]


def test_missing_token_and_invalid_arguments_fail_before_policy(monkeypatch):
    policy = Policy()
    app = build(monkeypatch, policy)
    with TestClient(app) as client:
        missing = call_body()
        missing["params"]["_meta"] = {}
        assert client.post("/mcp/tools/call", json=missing).status_code == 401
        invalid = call_body({"product_id": "not-a-uuid"})
        response = client.post("/mcp/tools/call", json=invalid)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_arguments"
    assert policy.calls == 0


def test_missing_scope_denied_locally(monkeypatch):
    async def no_scope(*_args, **_kwargs):
        claims = await verified()
        claims["scopes"] = ["portfolio:project:read"]
        return claims

    monkeypatch.setattr(server, "_verify_inner_token", no_scope)

    async def dispatch(*_args, **_kwargs):
        return product_result()

    monkeypatch.setattr(server, "_dispatch", dispatch)
    policy = Policy()
    app = server.build_server(policy, rate_limit_store=RateStore(), jwks_client=object())[2]
    with TestClient(app) as client:
        response = client.post("/mcp/tools/call", json=call_body())
    assert response.status_code == 403 and policy.calls == 0


def test_policy_deny_and_pending_never_dispatch(monkeypatch):
    async def forbidden_dispatch(*_args, **_kwargs):
        raise AssertionError("dispatch must not execute")

    monkeypatch.setattr(server, "_verify_inner_token", verified)
    monkeypatch.setattr(server, "_dispatch", forbidden_dispatch)
    for policy, expected in [
        (Policy("deny"), 403),
        (Policy("pending", "approval-1", "checkpoint-1"), 409),
    ]:
        app = server.build_server(policy, rate_limit_store=RateStore(), jwks_client=object())[2]
        with TestClient(app) as client:
            response = client.post("/mcp/tools/call", json=call_body())
        assert response.status_code == expected
    assert response.json()["pending"] == {
        "approvalUid": "approval-1",
        "checkpointUid": "checkpoint-1",
    }


def test_invalid_output_is_rejected(monkeypatch):
    monkeypatch.setattr(server, "_verify_inner_token", verified)

    async def bad(*_args, **_kwargs):
        return {"executed": "successfully"}

    monkeypatch.setattr(server, "_dispatch", bad)
    app = server.build_server(Policy(), rate_limit_store=RateStore(), jwks_client=object())[2]
    with TestClient(app) as client:
        response = client.post("/mcp/tools/call", json=call_body())
    assert response.status_code == 502
    assert response.json()["error"] == "invalid_tool_response"
