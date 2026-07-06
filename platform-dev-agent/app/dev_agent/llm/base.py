"""LLM seam protocols — a testable indirection over the chat model.

The personas (:class:`~app.dev_agent.profiles.base.ProfileBase`) and the leader
classifier (:class:`~app.dev_agent.orchestrator.DevOrchestrator`) never import a
concrete provider (no hardcoded ``LLMFactory``). They receive an
:class:`LLMProvider` by injection and ask it for an :class:`LLM`. In production
the provider wraps a langchain ``BaseChatModel`` (which already satisfies this
Protocol structurally: it exposes ``bind_tools`` / ``astream`` / ``ainvoke``);
in tests a fake object satisfying the same Protocol is passed instead.

The Protocols are intentionally minimal — exactly the surface the ReAct loop and
the classifier use:

- ``LLM.bind_tools(tools) -> LLM`` — return a tool-bound view of the model. The
  tools handed here are ALREADY guarded by capability (they arrive pre-wrapped);
  this method does not perform any authorization itself.
- ``LLM.astream(messages, **kw) -> AsyncIterator`` — stream response chunks
  (message chunks with ``.content`` and, on the aggregate, ``.tool_calls``).
- ``LLM.ainvoke(messages, **kw)`` — single-shot invocation (used by the leader
  for JSON classification).
- ``LLMProvider.get_llm(model) -> LLM`` — resolve a model code to an ``LLM``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLM(Protocol):
    """A chat model the ReAct loop and the classifier can drive.

    Structurally satisfied by a langchain ``BaseChatModel`` and by test fakes.
    """

    def bind_tools(self, tools: Sequence[Any]) -> "LLM":
        """Return a view of this model bound to ``tools`` (already guarded)."""
        ...

    def astream(self, messages: Sequence[Any], **kwargs: Any) -> AsyncIterator[Any]:
        """Stream response chunks for ``messages``.

        Returns an async iterator of message chunks. Each chunk exposes
        ``.content``; the aggregate (sum of chunks) exposes ``.tool_calls``.
        """
        ...

    async def ainvoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:
        """Invoke the model once and return the full response message."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Resolves a model code to an :class:`LLM` (injected, never hardcoded)."""

    def get_llm(self, model: str) -> LLM:
        """Return an :class:`LLM` for the given ``model`` code."""
        ...
