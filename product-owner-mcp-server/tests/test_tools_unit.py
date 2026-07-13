"""Unidade das tools que NÃO tocam o banco: o calculador determinístico de RICE
(dobrado em save_backlog_item) e os guards de validação que retornam antes do store."""

from __future__ import annotations

import pytest

from src.tools.backlog_item_tool import _maybe_rice_score, calculate_rice_score
from src.tools.po_artifact_tool import save_po_artifact


@pytest.mark.parametrize(
    "reach,impact,confidence,effort,expected",
    [
        (1000, 2, 0.8, 4, 400.0),  # (1000*2*0.8)/4
        (1000, 2, 80, 4, 400.0),  # confidence percentual 1-100 normaliza p/ 0-1
        (500, 1, 1.0, 2, 250.0),  # (500*1*1)/2
        (0, 3, 1.0, 1, 0.0),  # reach=0 -> score 0 (válido)
    ],
)
def test_calculate_rice_score_is_deterministic(reach, impact, confidence, effort, expected):
    out = calculate_rice_score(reach, impact, confidence, effort, feature="f")
    assert out["score"] == expected
    assert out["feature"] == "f"


@pytest.mark.parametrize(
    "reach,impact,confidence,effort",
    [
        (10, 2, 0.5, 0),  # effort=0 -> divisão por zero
        (10, 0, 0.5, 4),  # impact<=0
        (10, 2, 0, 4),  # confidence<=0
        (-1, 2, 0.5, 4),  # reach<0
        (10, 2, 200, 4),  # confidence fora de 0-1/1-100
    ],
)
def test_calculate_rice_score_rejects_invalid_input(reach, impact, confidence, effort):
    out = calculate_rice_score(reach, impact, confidence, effort)
    assert out["error"] == "invalid_input"
    assert out["details"]


def test_maybe_rice_score_requires_all_fields():
    assert _maybe_rice_score(None, 2, 0.8, 4) is None  # falta reach
    assert _maybe_rice_score(1000, 2, 0.8, 4) == 400.0
    assert _maybe_rice_score(10, 2, 0.5, 0) is None  # input inválido → None (sem score)


async def test_save_po_artifact_rejects_invalid_kind_before_store():
    # kind inválido → erro ANTES de tocar o store (store=None prova isso).
    out = await save_po_artifact(None, kind="nope", target="t")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
