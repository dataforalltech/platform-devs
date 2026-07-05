"""DevOrchestrator._detect_profile: classification, bypass, threshold, cache."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.dev_agent.orchestrator import DevOrchestrator


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeLeaderLLM:
    """Returns canned JSON on ainvoke; counts calls to prove caching."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0

    def bind_tools(self, tools):  # noqa: ANN001 - unused by the classifier
        return self

    def astream(self, messages, **kwargs):  # noqa: ANN001 - unused by the classifier
        raise NotImplementedError

    async def ainvoke(self, messages, **kwargs) -> _Resp:  # noqa: ANN001
        self.calls += 1
        return _Resp(json.dumps(self._payload))


def _orch(payload: dict[str, Any], **kw) -> tuple[DevOrchestrator, FakeLeaderLLM]:
    llm = FakeLeaderLLM(payload)
    return DevOrchestrator(tenant_id="t1", leader_llm=llm, **kw), llm


@pytest.mark.asyncio
async def test_canned_json_classification() -> None:
    orch, llm = _orch(
        {
            "profile": "backend",
            "sub_intent": "add_endpoint",
            "intent": "add a REST endpoint",
            "confidence": 0.92,
            "action_mode": "plan",
            "entity_type": "service",
        }
    )
    profile, intent, sub, action_mode, entity = await orch._detect_profile(
        "please add an endpoint", None
    )
    assert profile == "backend"
    assert sub == "add_endpoint"
    assert intent == "add a REST endpoint"
    assert action_mode == "plan"
    assert entity == "service"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_explicit_profile_bypasses_llm() -> None:
    orch, llm = _orch({"profile": "backend", "confidence": 0.9})
    profile, intent, sub, action_mode, entity = await orch._detect_profile(
        "whatever", "security"
    )
    assert profile == "security"
    assert action_mode == "analyze"
    assert entity is None
    assert llm.calls == 0  # explicit bypass never touches the LLM


@pytest.mark.asyncio
async def test_low_confidence_falls_back_to_architecture() -> None:
    orch, _ = _orch(
        {
            "profile": "backend",
            "confidence": 0.5,  # below the 0.6 threshold -> architecture
            "action_mode": "plan",
        }
    )
    profile, _intent, _sub, action_mode, _entity = await orch._detect_profile(
        "ambiguous request", None
    )
    assert profile == "architecture"
    assert action_mode == "plan"  # action_mode is independent of the fallback


@pytest.mark.asyncio
async def test_unknown_action_mode_becomes_analyze() -> None:
    orch, _ = _orch(
        {"profile": "devops", "confidence": 0.9, "action_mode": "nonsense"}
    )
    _profile, _intent, _sub, action_mode, _entity = await orch._detect_profile(
        "deploy something", None
    )
    assert action_mode == "analyze"


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_llm_call() -> None:
    orch, llm = _orch(
        {"profile": "qa_engineer", "confidence": 0.9, "action_mode": "analyze"}
    )
    r1 = await orch._detect_profile("Run The Tests  ", None)
    r2 = await orch._detect_profile("run the tests", None)  # normalized => same key
    assert r1 == r2
    assert llm.calls == 1  # second call served from cache


@pytest.mark.asyncio
async def test_bad_json_falls_back_gracefully() -> None:
    class _BadLLM(FakeLeaderLLM):
        async def ainvoke(self, messages, **kwargs):  # noqa: ANN001
            self.calls += 1
            return _Resp("not json at all")

    llm = _BadLLM({})
    orch = DevOrchestrator(tenant_id="t1", leader_llm=llm)
    profile, _intent, _sub, action_mode, _entity = await orch._detect_profile(
        "something", None
    )
    assert profile == "architecture"
    assert action_mode == "analyze"
