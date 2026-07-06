"""Unit tests for redaction of sensitive tool outputs (critique §2.7)."""

from __future__ import annotations

from app.dev_agent.security import SENSITIVE_TOOLS, redact


def test_sensitive_tool_output_is_redacted() -> None:
    secret = {"secret": "s3cr3t", "value": "AKIA..."}
    out = redact("config-mcp.get_secret", secret)
    assert out == {"__redacted__": True, "tool": "config-mcp.get_secret"}
    # None of the original payload survives.
    assert "secret" not in out
    assert "s3cr3t" not in str(out)


def test_jwt_tool_output_is_redacted() -> None:
    out = redact("auth-mcp.create_jwt", {"token": "eyJhbGci..."})
    assert out["__redacted__"] is True
    assert out["tool"] == "auth-mcp.create_jwt"
    assert "eyJhbGci" not in str(out)


def test_non_sensitive_tool_output_is_unchanged() -> None:
    payload = {"passed": 42, "failed": 0, "suite": "unit"}
    out = redact("qa-mcp.run_tests", payload)
    # Same object, untouched.
    assert out is payload
    assert out == {"passed": 42, "failed": 0, "suite": "unit"}


def test_sensitive_set_membership() -> None:
    assert "config-mcp.get_secret" in SENSITIVE_TOOLS
    assert "auth-mcp.create_api_key" in SENSITIVE_TOOLS
    assert "qa-mcp.run_tests" not in SENSITIVE_TOOLS
