from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "artifact-provenance-mcp-server"
sys.path[:0] = [str(ROOT), str(SERVICE)]

from artifact_provenance_mcp import server  # noqa: E402
from artifact_provenance_mcp.server import TOOLS, app  # noqa: E402
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
_SERVICE = "artifact-provenance-mcp"


def _mint_inner_token(*, audience: str = _SERVICE, tenant: str = "tenant-1", ttl: int = 600) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _INNER_ISSUER, "sub": "agent-1", "aud": f"mcp:{audience}",
            "iat": now, "exp": now + ttl, "tenant_id": tenant,
        },
        _INNER_PRIVATE_PEM, algorithm="RS256",
    )


def _configure_inner(monkeypatch) -> None:
    monkeypatch.setenv("MCP_INNER_TOKEN_ISSUER", _INNER_ISSUER)
    monkeypatch.setenv("MCP_INNER_TOKEN_PUBLIC_KEY", _INNER_PUBLIC_PEM)


def _headers(monkeypatch, *scopes: str) -> dict[str, str]:
    key = "runtime-test-key"
    monkeypatch.setenv("MCP_CONTEXT_SIGNING_KEY", key)
    _configure_inner(monkeypatch)
    payload = {
        "actor_id": "agent-1", "actor_type": "agent", "tenant_id": "tenant-1",
        "scopes": list(scopes), "environment": "test", "correlation_id": "corr-2",
        "issued_at": int(time.time()), "policy_decision_id": "decision-2", "approval_ids": [],
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return {"X-MCP-Context": encoded, "X-MCP-Context-Signature": signature, "X-MCP-Inner-Token": _mint_inner_token()}


def _call(client: TestClient, headers: dict[str, str], name: str, arguments: dict) -> dict:
    response = client.post(
        "/mcp/tools/call", headers=headers,
        json={"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "error" not in payload
    return payload["result"]


def test_all_provenance_tools_have_contracts_and_observable_behavior(monkeypatch) -> None:
    client = TestClient(app)
    catalog = load_catalog(ROOT)
    assert {tool.name for tool in TOOLS} == {name for provider, name in catalog.contracts if provider == "artifact-provenance-mcp"}
    for tool in TOOLS:
        contract = catalog.contracts[("artifact-provenance-mcp", tool.name)]
        assert contract.input_schema == tool.input_schema
        assert contract.output_schema == tool.output_schema
        assert contract.required_scope == tool.required_scope

    description = _call(client, _headers(monkeypatch, "provenance:read"), "provenance_hash_artifact", {"path": "README.md"})
    expected = hashlib.sha256((ROOT / "README.md").read_bytes()).hexdigest()
    assert description["sha256"] == expected
    assert description["size_bytes"] > 0

    verified = _call(
        client, _headers(monkeypatch, "provenance:verify"), "provenance_verify_artifact",
        {"path": "README.md", "expected_sha256": expected},
    )
    assert verified["matches"] is True

    statement = _call(
        client, _headers(monkeypatch, "provenance:read"), "provenance_build_statement",
        {"paths": ["README.md", "AGENTS.md"]},
    )
    assert [item["path"] for item in statement["subject"]] == ["README.md", "AGENTS.md"]
    assert statement["correlation_id"] == "corr-2"


def test_sensitive_and_escaping_paths_fail_without_leaking_path(monkeypatch) -> None:
    response = TestClient(app).post(
        "/mcp/tools/call", headers=_headers(monkeypatch, "provenance:read"),
        json={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "provenance_hash_artifact", "arguments": {"path": ".env"}}},
    )
    assert response.status_code == 200
    assert response.json()["error"]["message"] == "tool execution failed"
    assert ".env" not in json.dumps(response.json())


def test_invalid_signature_and_missing_decision_are_rejected(monkeypatch) -> None:
    headers = _headers(monkeypatch, "provenance:read")
    headers["X-MCP-Context-Signature"] = "0" * 64
    assert TestClient(app).get("/mcp/tools/list", headers=headers).status_code == 401

    key = "runtime-test-key"
    payload = {
        "actor_id": "agent-1", "actor_type": "agent", "tenant_id": "tenant-1",
        "scopes": ["provenance:read"], "environment": "test", "correlation_id": "corr",
        "issued_at": int(time.time()), "policy_decision_id": None, "approval_ids": [],
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    no_decision = {"X-MCP-Context": encoded, "X-MCP-Context-Signature": signature, "X-MCP-Inner-Token": _mint_inner_token()}
    response = TestClient(app).post(
        "/mcp/tools/call", headers=no_decision,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "provenance_hash_artifact", "arguments": {"path": "README.md"}}},
    )
    assert response.status_code == 403


def test_git_status_failure_is_reported_as_unknown(monkeypatch) -> None:
    # A non-zero `git status` (e.g. "dubious ownership" over a bind-mounted, foreign-owned
    # worktree) must degrade to git_status="unknown", never a hard tool failure.
    real_git = server._git

    def fake_git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        if "status" in arguments:
            return subprocess.CompletedProcess(list(arguments), 128, stdout="", stderr="dubious ownership")
        return real_git(*arguments, check=check)

    monkeypatch.setattr(server, "_git", fake_git)
    result = server.hash_artifact({"path": "README.md"}, None)
    assert result["git_status"] == "unknown"
    assert len(result["sha256"]) == 64
    assert result["size_bytes"] > 0


@pytest.mark.parametrize("name", [".pgpass", "id_dsa", "id_ecdsa", ".netrc", "_netrc"])
def test_resolve_rejects_extended_sensitive_names(tmp_path, monkeypatch, name: str) -> None:
    monkeypatch.setattr(server, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / name).write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="sensitive"):
        server._resolve_artifact(name)


def test_resolve_rejects_sensitive_directories(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="sensitive"):
        server._resolve_artifact(".ssh/config")


def _hash_call(client: TestClient, headers: dict[str, str]):
    return client.post(
        "/mcp/tools/call", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "provenance_hash_artifact", "arguments": {"path": "README.md"}}},
    )


def test_inner_token_wrong_audience_is_rejected(monkeypatch) -> None:
    headers = dict(_headers(monkeypatch, "provenance:read"))
    headers["X-MCP-Inner-Token"] = _mint_inner_token(audience="contracts-mcp")
    assert _hash_call(TestClient(app), headers).status_code == 401


def test_inner_token_expired_is_rejected(monkeypatch) -> None:
    headers = dict(_headers(monkeypatch, "provenance:read"))
    headers["X-MCP-Inner-Token"] = _mint_inner_token(ttl=-120)
    assert _hash_call(TestClient(app), headers).status_code == 401


def test_inner_token_tenant_mismatch_is_rejected(monkeypatch) -> None:
    headers = dict(_headers(monkeypatch, "provenance:read"))
    headers["X-MCP-Inner-Token"] = _mint_inner_token(tenant="tenant-evil")
    assert _hash_call(TestClient(app), headers).status_code == 401


def test_missing_inner_token_configuration_fails_closed(monkeypatch) -> None:
    headers = _headers(monkeypatch, "provenance:read")
    monkeypatch.delenv("MCP_INNER_TOKEN_ISSUER", raising=False)
    monkeypatch.delenv("MCP_INNER_TOKEN_PUBLIC_KEY", raising=False)
    assert _hash_call(TestClient(app), headers).status_code == 503


def test_stale_context_is_rejected(monkeypatch) -> None:
    key = "runtime-test-key"
    monkeypatch.setenv("MCP_CONTEXT_SIGNING_KEY", key)
    _configure_inner(monkeypatch)
    payload = {
        "actor_id": "agent-1", "actor_type": "agent", "tenant_id": "tenant-1",
        "scopes": ["provenance:read"], "environment": "test", "correlation_id": "corr",
        "issued_at": int(time.time()) - 10_000, "policy_decision_id": "d", "approval_ids": [],
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    headers = {"X-MCP-Context": encoded, "X-MCP-Context-Signature": signature, "X-MCP-Inner-Token": _mint_inner_token()}
    assert _hash_call(TestClient(app), headers).status_code == 401


def test_missing_scope_is_denied(monkeypatch) -> None:
    # F9: the deny path still returns 403 (and now emits a provider audit event).
    assert _hash_call(TestClient(app), _headers(monkeypatch, "unrelated:read")).status_code == 403


def test_build_statement_enforces_aggregate_budget(monkeypatch) -> None:
    monkeypatch.setattr(server, "_MAX_STATEMENT_BYTES", 1)
    with pytest.raises(ValueError, match="aggregate hashing budget"):
        server.build_statement({"paths": ["README.md"]}, None)
