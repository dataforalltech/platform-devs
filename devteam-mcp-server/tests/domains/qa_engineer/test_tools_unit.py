# Portado de `qa-engineer-mcp-server/tests/test_tools_unit.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade das tools que NÃO tocam o banco: o classificador determinístico de bug
(dobrado em save_bug_report) e os guards de validação que retornam antes do store."""

from __future__ import annotations

import importlib

import pytest

_mod_tools_artifact_tool = importlib.import_module("src.domains.qa-engineer.tools.artifact_tool")
save_artifact = _mod_tools_artifact_tool.save_artifact
_mod_tools_bug_report_tool = importlib.import_module("src.domains.qa-engineer.tools.bug_report_tool")
classify_bug_severity = _mod_tools_bug_report_tool.classify_bug_severity
save_bug_report = _mod_tools_bug_report_tool.save_bug_report


@pytest.mark.parametrize(
    "impact,frequency,severity,score",
    [
        ("critical", "always", "P1", 16.0),  # 4*4
        ("high", "often", "P1", 9.0),  # 3*3 -> >=9
        ("medium", "often", "P2", 6.0),  # 2*3
        ("medium", "sometimes", "P3", 4.0),  # 2*2
        ("low", "rarely", "P4", 1.0),  # 1*1
        ("desconhecido", "xpto", "P3", 4.0),  # defaults 2*2
    ],
)
def test_classify_bug_severity_is_deterministic(impact, frequency, severity, score):
    assert classify_bug_severity(impact, frequency) == (severity, score)


async def test_save_bug_report_rejects_invalid_severity_before_store():
    # severity explícita inválida → erro ANTES de tocar o store (store=None prova isso).
    out = await save_bug_report(None, title="x", severity="P9")  # type: ignore[arg-type]
    assert out["error"] == "invalid_severity"


async def test_save_artifact_rejects_invalid_kind_before_store():
    out = await save_artifact(None, kind="nope", target="t", content="c")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
