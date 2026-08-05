# Portado de `backend-mcp-server/tests/test_tools_unit.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade das tools que NÃO tocam o banco: o normalizador determinístico de método
HTTP e os guards de validação que retornam antes do store."""

from __future__ import annotations

import pytest

from src.domains.backend.tools.api_contract_tool import normalize_method, save_api_contract
from src.domains.backend.tools.artifact_tool import save_artifact


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("get", "GET"),
        (" Post ", "POST"),
        ("PATCH", "PATCH"),
        ("delete", "DELETE"),
    ],
)
def test_normalize_method_is_deterministic(raw, expected):
    assert normalize_method(raw) == expected


async def test_save_api_contract_rejects_invalid_method_before_store():
    # método inválido → erro ANTES de tocar o store (store=None prova isso).
    out = await save_api_contract(None, endpoint="/x", method="FETCH")  # type: ignore[arg-type]
    assert out["error"] == "invalid_method"


async def test_save_artifact_rejects_invalid_kind_before_store():
    out = await save_artifact(None, kind="nope", target="t", content="c")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
