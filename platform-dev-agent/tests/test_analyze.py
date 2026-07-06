"""``analyze`` path E2E — a persona converses via the gateway, capability-guarded.

Drives :meth:`DevOrchestrator.run_analyze` with a fake LLM that first emits ONE
tool call and then a final text turn, over the real httpx stack against the
in-process fake gateway (``httpx.ASGITransport``). Asserts:

1. the persona's read tool actually traversed the gateway (recorded in
   ``FakeGateway.idempotency_keys``) and the final text was streamed back;
2. a write tool for a READ-only persona is denied by the single enforcer with a
   :class:`CapabilityViolation` *before* it can reach the gateway, and the
   persona surfaces that as a tool error instead of aborting the stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest

from app.dev_agent.capability import (
    Capability,
    CapabilityEnforcer,
    CapabilityResolver,
    CapabilityViolation,
)
from app.dev_agent.gateway.client import GatewayToolClient
from app.dev_agent.gateway.tool_provider import GatewayToolProvider, ToolSpec
from app.dev_agent.orchestrator import DevOrchestrator
from tests._fake_gateway import FakeGateway, StaticTokenProvider

# A read tool the fake gateway actually serves (from its canned catalog).
_READ_TOOL = "services-mcp.check_health"
# A write tool: verb prefix "create_" => WRITE via the resolver's heuristic.
_WRITE_TOOL = "deploy-mcp.create_deployment"
# READ-only persona present in PROFILES (knowledge/profiles/qa_engineer.md).
_READ_ONLY_PROFILE = "qa_engineer"
_FINAL_TEXT = "Service is healthy; nothing to escalate."


# --------------------------------------------------------------------------- #
# Fake LLM satisfying the LLM / LLMProvider Protocols (llm/base.py).
# --------------------------------------------------------------------------- #
class _Chunk:
    """A minimal message chunk: ``.content`` (text) + optional ``.tool_calls``."""

    def __init__(self, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeLLM:
    """Two-turn ReAct fake: turn 1 emits one tool call, turn 2 emits final text.

    ``bind_tools`` returns ``self`` (the fake ignores binding; the guard lives in
    the tool objects, not the model). Structurally satisfies ``LLM``.
    """

    def __init__(self, tool_name: str) -> None:
        self._tool_name = tool_name
        self._turn = 0

    def bind_tools(self, tools: Sequence[Any]) -> "_FakeLLM":
        return self

    async def ainvoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:
        return _Chunk(content=_FINAL_TEXT)

    async def astream(self, messages: Sequence[Any], **kwargs: Any) -> AsyncIterator[_Chunk]:
        self._turn += 1
        if self._turn == 1:
            # One tool call, no assistant text this turn (drives the ReAct loop).
            yield _Chunk(
                content="",
                tool_calls=[{"name": self._tool_name, "args": {"service": "api"}, "id": "call-1"}],
            )
        else:
            # Final answer: plain text, no tool calls => loop ends.
            yield _Chunk(content=_FINAL_TEXT)


class _FakeLLMProvider:
    """Resolves any model code to the same ``_FakeLLM`` (satisfies ``LLMProvider``)."""

    def __init__(self, llm: _FakeLLM) -> None:
        self._llm = llm

    def get_llm(self, model: str) -> _FakeLLM:
        return self._llm


def _make_orchestrator(fake: FakeGateway) -> DevOrchestrator:
    client = GatewayToolClient(
        base_url="http://gateway.local/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )
    # qa_engineer is READ-only; the enforcer denies it WRITE.
    enforcer = CapabilityEnforcer({_READ_ONLY_PROFILE: {Capability.READ}})
    provider = GatewayToolProvider(client, enforcer, caps=CapabilityResolver())
    return DevOrchestrator(
        tenant_id="acme",
        leader_llm=_FakeLLM(_READ_TOOL),  # unused by run_analyze; harmless
        tool_provider=provider,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_analyze_calls_read_tool_via_gateway_and_streams_final_text() -> None:
    fake = FakeGateway()
    orch = _make_orchestrator(fake)

    tokens: list[str] = []
    async for tok in orch.run_analyze(
        "Is the service healthy?",
        profile=_READ_ONLY_PROFILE,
        session_id="s1",
        tool_specs=[ToolSpec(name=_READ_TOOL, description="check service health")],
        llm_provider=_FakeLLMProvider(_FakeLLM(_READ_TOOL)),
        run_id="run-analyze-1",
        tenant_id="acme",
    ):
        tokens.append(tok)

    # (1) the read tool really traversed the gateway (idempotency key recorded).
    called_tools = [tool for tool, _ in fake.idempotency_keys]
    assert _READ_TOOL in called_tools
    idem = dict(fake.idempotency_keys)[_READ_TOOL]
    assert idem  # an Idempotency-Key was always sent

    # (2) the persona streamed the final text back.
    assert "".join(tokens).strip() == _FINAL_TEXT


@pytest.mark.asyncio
async def test_write_tool_for_read_only_profile_raises_capability_violation() -> None:
    """The single enforcer denies WRITE to a READ-only persona, before the gateway."""
    fake = FakeGateway()
    client = GatewayToolClient(
        base_url="http://gateway.local/mcp",
        token_provider=StaticTokenProvider(),
        transport=httpx.ASGITransport(app=fake.app),
    )
    enforcer = CapabilityEnforcer({_READ_ONLY_PROFILE: {Capability.READ}})
    provider = GatewayToolProvider(client, enforcer, caps=CapabilityResolver())

    [tool] = provider.build_tools(
        profile_id=_READ_ONLY_PROFILE,
        specs=[ToolSpec(name=_WRITE_TOOL, description="create a deployment")],
        run_id="run-x",
        session_id="s1",
        tenant_id="acme",
    )

    with pytest.raises(CapabilityViolation):
        await tool.ainvoke({"environment": "prod"})

    # Denied at the guard: nothing ever reached the gateway.
    assert fake.idempotency_keys == []


@pytest.mark.asyncio
async def test_analyze_surfaces_write_denial_as_tool_error_not_abort() -> None:
    """A denied write inside the ReAct loop becomes a tool error; the stream finishes."""
    fake = FakeGateway()
    orch = _make_orchestrator(fake)

    tokens: list[str] = []
    async for tok in orch.run_analyze(
        "Deploy the new build.",
        profile=_READ_ONLY_PROFILE,
        session_id="s2",
        tool_specs=[ToolSpec(name=_WRITE_TOOL, description="create a deployment")],
        # This provider's LLM asks for the WRITE tool on turn 1, then finalizes.
        llm_provider=_FakeLLMProvider(_FakeLLM(_WRITE_TOOL)),
        run_id="run-analyze-2",
        tenant_id="acme",
    ):
        tokens.append(tok)

    # The write was denied before the gateway (no dispatch recorded)...
    assert fake.idempotency_keys == []
    # ...and the loop still reached its final text instead of aborting.
    assert "".join(tokens).strip() == _FINAL_TEXT
