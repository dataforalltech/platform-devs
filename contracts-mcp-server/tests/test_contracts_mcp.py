from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = ROOT / "contracts-mcp-server"
sys.path[:0] = [str(ROOT), str(SERVICE_DIR)]

from contracts_mcp.server import TOOLS, app  # noqa: E402
from src.control_plane.manifest_loader import load_catalog  # noqa: E402

_INNER_ISSUER = "https://as.test/inner"
_INNER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_INNER_PRIVATE_PEM = _INNER_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_INNER_PUBLIC_PEM = _INNER_KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()
_SERVICE = "contracts-mcp"


def _mint_inner_token(*, audience: str = _SERVICE, tenant: str = "tenant-1", ttl: int = 600) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _INNER_ISSUER, "sub": "agent-1", "aud": f"mcp:{audience}",
            "iat": now, "exp": now + ttl, "tenant_id": tenant,
        },
        _INNER_PRIVATE_PEM, algorithm="RS256",
    )


def _headers(monkeypatch, *scopes: str, decision: str | None = "decision-1") -> dict[str, str]:
    key = "runtime-test-key"
    monkeypatch.setenv("MCP_CONTEXT_SIGNING_KEY", key)
    monkeypatch.setenv("MCP_INNER_TOKEN_ISSUER", _INNER_ISSUER)
    monkeypatch.setenv("MCP_INNER_TOKEN_PUBLIC_KEY", _INNER_PUBLIC_PEM)
    payload = {
        "actor_id": "agent-1", "actor_type": "agent", "tenant_id": "tenant-1",
        "scopes": list(scopes), "environment": "test", "correlation_id": "corr-1",
        "issued_at": int(time.time()), "policy_decision_id": decision, "approval_ids": [],
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return {"X-MCP-Context": encoded, "X-MCP-Context-Signature": signature, "X-MCP-Inner-Token": _mint_inner_token()}


def _call(client: TestClient, headers: dict[str, str], name: str, arguments: dict) -> dict:
    response = client.post(
        "/mcp/tools/call",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    )
    assert response.status_code == 200
    return response.json()


def test_direct_tool_metadata_requires_gateway_credentials(monkeypatch) -> None:
    monkeypatch.setenv("MCP_CONTEXT_SIGNING_KEY", "runtime-test-key")
    assert TestClient(app).get("/mcp/tools/list").status_code == 401


def test_list_exposes_input_output_and_security_contracts(monkeypatch) -> None:
    response = TestClient(app).get("/mcp/tools/list", headers=_headers(monkeypatch, "contracts:read", decision=None))
    assert response.status_code == 200
    listed = response.json()["result"]["tools"]
    assert {item["name"] for item in listed} == {item.name for item in TOOLS}
    assert all("inputSchema" in item and "outputSchema" in item and "security" in item for item in listed)


def test_all_contract_tools_have_canonical_contracts_and_behavior(monkeypatch) -> None:
    client = TestClient(app)
    catalog = load_catalog(ROOT)
    assert {tool.name for tool in TOOLS} == {name for provider, name in catalog.contracts if provider == "contracts-mcp"}
    for tool in TOOLS:
        contract = catalog.contracts[("contracts-mcp", tool.name)]
        assert contract.input_schema == tool.input_schema
        assert contract.output_schema == tool.output_schema
        assert contract.required_scope == tool.required_scope

    listed = _call(client, _headers(monkeypatch, "contracts:read"), "contracts_list", {})["result"]
    assert listed["count"] == len(catalog.contracts)
    assert any(item["provider_id"] == "contracts-mcp" for item in listed["contracts"])

    found = _call(
        client, _headers(monkeypatch, "contracts:read"), "contracts_get",
        {"provider_id": "contracts-mcp", "name": "contracts_get"},
    )["result"]
    assert found["found"] is True
    assert found["contract"]["required_scope"] == "contracts:read"

    validation = _call(
        client, _headers(monkeypatch, "contracts:validate"), "contracts_validate_catalog", {},
    )["result"]
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_input_and_scope_are_enforced(monkeypatch) -> None:
    client = TestClient(app)
    response = client.post(
        "/mcp/tools/call", headers=_headers(monkeypatch, "contracts:read"),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "contracts_list", "arguments": {"unexpected": True}}},
    )
    assert response.status_code == 400
    response = client.post(
        "/mcp/tools/call", headers=_headers(monkeypatch, "unrelated:read"),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "contracts_list", "arguments": {}}},
    )
    assert response.status_code == 403


def test_inner_token_audience_binding_is_enforced(monkeypatch) -> None:
    headers = dict(_headers(monkeypatch, "contracts:read"))
    # A token minted for another provider audience must not be accepted here.
    headers["X-MCP-Inner-Token"] = _mint_inner_token(audience="artifact-provenance-mcp")
    response = TestClient(app).post(
        "/mcp/tools/call", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "contracts_list", "arguments": {}}},
    )
    assert response.status_code == 401


def test_missing_inner_token_configuration_fails_closed(monkeypatch) -> None:
    headers = _headers(monkeypatch, "contracts:read")
    monkeypatch.delenv("MCP_INNER_TOKEN_ISSUER", raising=False)
    monkeypatch.delenv("MCP_INNER_TOKEN_PUBLIC_KEY", raising=False)
    response = TestClient(app).post(
        "/mcp/tools/call", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "contracts_list", "arguments": {}}},
    )
    assert response.status_code == 503
