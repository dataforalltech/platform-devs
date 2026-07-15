"""Unidade das tools que NÃO tocam o banco: os guards de validação que retornam
antes do store (com store=None provando que o banco não é tocado)."""

from __future__ import annotations

from src.tools.artifact_tool import VALID_KINDS, save_artifact


def test_valid_kinds_cover_the_four_ui_types():
    # os 4 tipos gerados pelas antigas tools generate_* continuam válidos como artefato.
    assert {"react_component", "nextjs_page", "form", "storybook_story"} <= VALID_KINDS


async def test_save_artifact_rejects_invalid_kind_before_store():
    # kind inválido → erro ANTES de tocar o store (store=None prova isso).
    out = await save_artifact(None, kind="nope", target="t", content="c")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
    assert "nope" not in out["valid"]
