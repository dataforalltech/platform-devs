"""LLM seam for the dev agent.

A tiny, testable indirection layer between the personas / leader classifier and
whatever concrete chat model backs them (langchain, a stub, a fake). Nothing in
``app.dev_agent`` binds a hardcoded provider: the :class:`LLMProvider` is always
injected, so tests can pass a fake that returns canned output without a network
call.

See :mod:`app.dev_agent.llm.base` for the :class:`LLM` and :class:`LLMProvider`
protocols.
"""

from app.dev_agent.llm.base import LLM, LLMProvider

__all__ = ["LLM", "LLMProvider"]
