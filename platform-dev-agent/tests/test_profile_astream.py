"""ProfileBase.astream ReAct loop: one tool_call, then final text.

A FakeLLM (satisfying the LLM seam Protocol) emits, on the first turn, a chunk
carrying one tool_call and, on the second turn (after the tool result is fed
back), the final text. We assert the tool was invoked with the given args and
that the final text is streamed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.dev_agent.profiles.backend import BackendProfile


class _Chunk:
    """A minimal message chunk: text content + optional tool_calls."""

    def __init__(self, content: str = "", tool_calls: list[dict] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def __add__(self, other: "_Chunk") -> "_Chunk":
        return _Chunk(
            content=(self.content or "") + (other.content or ""),
            tool_calls=self.tool_calls or other.tool_calls,
        )


class FakeLLM:
    """Emits one tool_call turn, then a final-text turn. No network."""

    def __init__(self) -> None:
        self._turn = 0
        self.bound_tools: list[Any] | None = None

    def bind_tools(self, tools):  # noqa: ANN001
        self.bound_tools = list(tools)
        return self

    def astream(self, messages, **kwargs) -> AsyncIterator[_Chunk]:  # noqa: ANN001
        turn = self._turn
        self._turn += 1

        async def _gen() -> AsyncIterator[_Chunk]:
            if turn == 0:
                yield _Chunk(
                    tool_calls=[
                        {"name": "run_tests", "args": {"suite": "unit"}, "id": "call-1"}
                    ]
                )
            else:
                yield _Chunk(content="All ")
                yield _Chunk(content="tests passed.")

        return _gen()

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001 - unused here
        raise NotImplementedError


class _FakeProvider:
    def __init__(self, llm: FakeLLM) -> None:
        self._llm = llm

    def get_llm(self, model: str) -> FakeLLM:
        return self._llm


class _RecordingTool:
    """A guarded-tool stand-in: records ainvoke args, returns a fixed result."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> str:
        self.calls.append(args)
        return "ran 12 tests, 12 passed"


@pytest.mark.asyncio
async def test_astream_runs_tool_then_streams_final_text() -> None:
    llm = FakeLLM()
    tool = _RecordingTool("run_tests")
    profile = BackendProfile(tools=[tool], llm_provider=_FakeProvider(llm))

    chunks = [tok async for tok in profile.astream("run the unit suite")]
    text = "".join(chunks)

    # The tool was invoked exactly once with the tool_call args.
    assert tool.calls == [{"suite": "unit"}]
    # The final text was streamed.
    assert text == "All tests passed."
    # bind_tools received the guarded tool.
    assert llm.bound_tools == [tool]


@pytest.mark.asyncio
async def test_astream_reads_prompt_body_from_file() -> None:
    """system_prompt() returns the markdown body (no front-matter leakage)."""
    profile = BackendProfile(tools=[], llm_provider=_FakeProvider(FakeLLM()))
    body = profile.system_prompt()
    assert "Backend Engineer" in body
    assert "---" not in body.splitlines()[0]  # front-matter fence not in body
    assert "id: backend" not in body
