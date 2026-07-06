"""``ProfileBase`` — a persona's ReAct loop over the injected LLM seam.

Ported (in *form*) from the marketing agent's ``profiles/base.py`` ReAct loop,
with the locked corrections:

1. ``system_prompt()`` READS ``knowledge/profiles/<id>.md`` (body only, no
   front-matter) — never an embedded string.
2. tools already arrive **guarded by capability** (the orchestrator wraps them
   before construction); this class does no arbitrary bind / authorization.
3. ``max_iterations`` is a real per-profile class attribute (front-matter can
   override via the loader) — no phantom ``agent_max_iterations``.
4. the LLM is reached through the injected :class:`LLMProvider` seam — there is
   no hardcoded factory, so a fake provider drives the loop under test.
"""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC
from pathlib import Path
from typing import Any, ClassVar

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.dev_agent.llm.base import LLM, LLMProvider

logger = logging.getLogger(__name__)

# Root of the persona prompt files — the SINGLE source of a persona's prompt.
# Derived from the repo layout (app/dev_agent/profiles/base.py -> repo root),
# independent of Settings so this module has no phantom config dependency.
PROFILES_DIR: Path = (
    Path(__file__).resolve().parents[3] / "knowledge" / "profiles"
)

# Per-tool / per-stream ceilings. Local constants (not phantom Settings fields)
# so the ReAct loop cannot hang indefinitely.
STREAM_TIMEOUT_S: float = 120.0
TOOL_TIMEOUT_S: float = 60.0
TOOL_MAX_RETRIES: int = 2

_FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


class ProfileParseError(RuntimeError):
    """Persona front-matter / markdown is invalid — explicit failure, no silent fallback."""


def _split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    """Split ``---\\n<yaml>\\n---\\n<body>`` into ``(meta, body)``.

    Shared by :meth:`ProfileBase._load_prompt_body` and the loader so the parse
    rule lives in one place. Raises :class:`ProfileParseError` when there is no
    YAML front-matter block.
    """
    import yaml  # local import: keep yaml optional at import time of this module

    match = _FRONT_MATTER_RE.match(raw)
    if not match:
        raise ProfileParseError(
            "persona file has no YAML front-matter block (--- ... ---)"
        )
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ProfileParseError("persona front-matter must be a YAML mapping")
    return meta, match.group(2)


def _extract_text(content: Any) -> str:
    """Extract plain text from a message chunk's ``content``.

    langchain content is either a ``str`` or a list of parts (dicts/objects);
    only text parts contribute to the streamed tokens.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content)


async def _invoke_tool_with_retry(tool: Any, args: dict[str, Any]) -> Any:
    """Invoke ``tool.ainvoke(args)`` with a small timeout + retry.

    The tool is already capability-guarded; a guarded WRITE denial raises and is
    surfaced as a tool error (never a false success).
    """
    last: Exception | None = None
    for attempt in range(TOOL_MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(tool.ainvoke(args), timeout=TOOL_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - re-raised after retries
            last = exc
            if attempt < TOOL_MAX_RETRIES:
                await asyncio.sleep(0.2 * (attempt + 1))
    assert last is not None  # loop always sets last before falling through
    raise last


class ProfileBase(ABC):
    """Base persona: identity + a ReAct ``astream`` over the injected LLM."""

    # Identity — overridable by subclass and/or filled from front-matter (loader).
    id: ClassVar[str] = ""  # e.g. "backend" — matches knowledge/profiles/backend.md
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    model: ClassVar[str] = "claude-sonnet-4-6"
    max_iterations: ClassVar[int] = 12  # real, per-profile
    front_matter: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        tools: list[Any] | None = None,
        *,
        llm_provider: LLMProvider,
    ) -> None:
        # ``tools`` already arrive guarded by CapabilityGuard (orchestrator wires
        # them). This class never binds arbitrary/unguarded tools.
        self._tools: list[Any] = list(tools or [])
        self._llm_provider: LLMProvider = llm_provider

    @property
    def tools(self) -> list[Any]:
        return self._tools

    # ---- Prompt in FILE (replaces the marketing agent's hardcoded prompt) ----
    def system_prompt(self) -> str:
        return self._load_prompt_body()

    def _prompt_path(self) -> Path:
        return PROFILES_DIR / f"{self.id}.md"

    def _load_prompt_body(self) -> str:
        raw = self._prompt_path().read_text(encoding="utf-8")
        _meta, body = _split_front_matter(raw)
        if not body.strip():
            raise ProfileParseError(f"empty prompt body for persona {self.id!r}")
        return body

    def build_messages(
        self,
        user_message: str,
        history: list[BaseMessage] | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[BaseMessage]:
        system = self.system_prompt()
        if context:
            ctx = "\n".join(f"{k}: {v}" for k, v in context.items())
            system = f"{system}\n\n## Context\n{ctx}"
        msgs: list[BaseMessage] = [SystemMessage(content=system)]
        if history:
            msgs.extend(history)
        msgs.append(HumanMessage(content=user_message))
        return msgs

    def _build_llm(self) -> LLM:
        llm = self._llm_provider.get_llm(self.model)
        if self._tools:
            llm = llm.bind_tools(self._tools)  # tools already guarded by capability
        return llm

    async def astream(
        self,
        user_message: str,
        *,
        history: list[BaseMessage] | None = None,
        context: dict[str, Any] | None = None,
        callbacks: list[Any] | None = None,
    ):
        """Stream the persona's response, running tools via the ReAct loop.

        Yields text tokens as they arrive. Each iteration streams one LLM turn;
        if the aggregated turn has ``tool_calls`` they are executed (via the
        already-guarded ``tool.ainvoke``) and their outputs fed back as
        ``ToolMessage`` for the next iteration. The loop ends when a turn has no
        tool calls or ``max_iterations`` is reached.
        """
        llm = self._build_llm()
        messages: list[BaseMessage] = self.build_messages(user_message, history, context)
        tool_map = {getattr(t, "name", None): t for t in self._tools}
        config = {"callbacks": callbacks} if callbacks else {}

        for _iteration in range(self.max_iterations):
            chunks: list[Any] = []
            try:
                iterator = _aiter(llm.astream(messages, config=config))
                while True:
                    chunk = await asyncio.wait_for(
                        iterator.__anext__(), timeout=STREAM_TIMEOUT_S
                    )
                    text = _extract_text(getattr(chunk, "content", None))
                    if text:
                        yield text
                    chunks.append(chunk)
            except StopAsyncIteration:
                pass
            except (TimeoutError, asyncio.TimeoutError):
                yield f"\n\n_(stream timeout of {STREAM_TIMEOUT_S:.0f}s reached)_"
                return

            if not chunks:
                break

            aggregate = _aggregate(chunks)
            tool_calls = getattr(aggregate, "tool_calls", None) or []
            if not tool_calls:
                break  # final answer

            messages.append(aggregate)
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args", {}) or {}
                call_id = call.get("id", "")
                tool = tool_map.get(name)
                if tool is None:
                    messages.append(
                        ToolMessage(
                            content=f"tool {name!r} unavailable for this profile",
                            tool_call_id=call_id,
                        )
                    )
                    continue
                try:
                    result = await _invoke_tool_with_retry(tool, args)
                    messages.append(
                        ToolMessage(content=str(result), tool_call_id=call_id)
                    )
                except Exception as exc:  # noqa: BLE001 - surfaced as tool error
                    messages.append(
                        ToolMessage(
                            content=f"error running tool: {exc}",
                            tool_call_id=call_id,
                        )
                    )


def _aiter(maybe_iterable: Any):
    """Return an async iterator from ``llm.astream(...)``.

    ``astream`` may return an async iterator directly or (rarely) a coroutine
    that resolves to one; normalise to an iterator with ``__anext__``.
    """
    if hasattr(maybe_iterable, "__anext__"):
        return maybe_iterable
    if hasattr(maybe_iterable, "__aiter__"):
        return maybe_iterable.__aiter__()
    raise TypeError("llm.astream did not return an async iterator")


def _aggregate(chunks: list[Any]) -> Any:
    """Aggregate streamed chunks into a single message.

    langchain message chunks support ``+``; if that fails (e.g. a plain fake
    that already yields whole messages) fall back to the last chunk, which is
    where a fake would carry the final ``tool_calls``.
    """
    aggregate = chunks[0]
    for chunk in chunks[1:]:
        try:
            aggregate = aggregate + chunk
        except Exception:  # noqa: BLE001 - fall back below
            aggregate = chunk
    # If the aggregate has no tool_calls but a later chunk does, prefer it.
    if not getattr(aggregate, "tool_calls", None):
        for chunk in reversed(chunks):
            if getattr(chunk, "tool_calls", None):
                return chunk
    return aggregate


__all__ = [
    "ProfileBase",
    "ProfileParseError",
    "PROFILES_DIR",
    "_split_front_matter",
    "_extract_text",
    "AIMessage",
]
