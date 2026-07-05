"""Redaction of sensitive tool outputs before persist / LLM re-injection (critique §2.7).

Some gateway tools return secrets — ``config-mcp.get_secret``,
``auth-mcp.create_jwt``, etc. Their raw output must NEVER reach the plan store
(``dev_plan_items.output_json``) nor be re-injected into the LLM context, or a
secret leaks into logs, the DB, and the model's transcript.

:func:`redact` is applied to a tool's output the moment it comes back from the
gateway, BEFORE it is persisted or put on an ``ItemResult``. A sensitive tool's
payload is replaced by a small marker ``{"__redacted__": True, "tool": <tool>}``;
any non-sensitive tool's output passes through unchanged.
"""

from __future__ import annotations

from typing import Any

# Tools whose output is sensitive and must be redacted before persist/re-inject.
# Namespaced gateway ids ("<namespace>.<operationId>"), matched exactly.
SENSITIVE_TOOLS: frozenset[str] = frozenset(
    {
        "config-mcp.get_secret",
        "config-mcp.get_config",
        "config-mcp.list_secrets",
        "config-mcp.export_config",
        "auth-mcp.create_jwt",
        "auth-mcp.create_api_key",
        "auth-mcp.refresh_token",
    }
)


def redact(tool: str, output: Any) -> Any:
    """Return ``output`` unchanged, or a redaction marker if ``tool`` is sensitive.

    The marker deliberately keeps NONE of the original payload — only the fact
    that a value existed and which tool produced it — so nothing sensitive is
    persisted or re-injected. Non-sensitive tools pass through untouched (same
    object, not a copy).
    """
    if tool in SENSITIVE_TOOLS:
        return {"__redacted__": True, "tool": tool}
    return output
