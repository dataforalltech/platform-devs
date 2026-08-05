# Portado de `product-manager-mcp-server/tests/test_tools_unit.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade das tools que NÃO tocam o banco: os guards de validação que retornam antes
do store (ex.: kind inválido de artefato) e o conjunto de kinds válidos."""

from __future__ import annotations

import importlib

_mod_tools_artifact_tool = importlib.import_module("src.domains.product-manager.tools.artifact_tool")
VALID_KINDS = _mod_tools_artifact_tool.VALID_KINDS
save_artifact = _mod_tools_artifact_tool.save_artifact


def test_valid_kinds_cover_the_four_first_class():
    # os 4 artefatos first-class do persona são kinds válidos de PmArtifact.
    assert {"product_vision", "feature_spec", "gtm_brief", "release_plan"} <= VALID_KINDS


async def test_save_artifact_rejects_invalid_kind_before_store():
    # kind inválido → erro ANTES de tocar o store (store=None prova isso).
    out = await save_artifact(None, kind="nope", target="t", content="c")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
    assert "nope" not in out["valid"]
