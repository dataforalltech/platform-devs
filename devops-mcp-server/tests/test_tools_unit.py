"""Unidade das tools que NÃO tocam o banco: o recomendador determinístico de
estratégia de rollout (dobrado em save_deployment) e os guards de validação que
retornam antes do store."""

from __future__ import annotations

import pytest

from src.tools.artifact_tool import save_artifact
from src.tools.deployment_tool import recommend_strategy
from src.tools.environment_tool import set_environment
from src.tools.pipeline_tool import save_pipeline, update_pipeline


@pytest.mark.parametrize(
    "environment,strategy",
    [
        ("prod", "blue_green"),
        ("PRODUCTION", "blue_green"),  # case-insensitive
        ("prd", "blue_green"),
        ("hml", "rolling"),
        ("staging", "rolling"),
        ("dev", "recreate"),
        (" local ", "recreate"),  # trim
        ("desconhecido", "rolling"),  # default
    ],
)
def test_recommend_strategy_is_deterministic(environment, strategy):
    assert recommend_strategy(environment) == strategy


async def test_save_artifact_rejects_invalid_kind_before_store():
    # kind inválido → erro ANTES de tocar o store (store=None prova isso).
    out = await save_artifact(None, kind="nope", target="t", content="c")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"


async def test_save_pipeline_rejects_invalid_provider_before_store():
    out = await save_pipeline(None, application="a", provider="nope")  # type: ignore[arg-type]
    assert out["error"] == "invalid_provider"


async def test_update_pipeline_rejects_invalid_provider_before_store():
    out = await update_pipeline(None, pipeline_id=1, provider="nope")  # type: ignore[arg-type]
    assert out["error"] == "invalid_provider"


async def test_set_environment_rejects_invalid_kind_before_store():
    out = await set_environment(None, name="c1", kind="nope")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
