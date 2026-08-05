# Portado de `security-mcp-server/tests/test_tools_unit.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Unidade das tools que NÃO tocam o banco: os cálculos determinísticos (CVSS v3.1
dobrado em save_cvss_assessment; política de senha NIST) e os guards de validação que
retornam antes do store."""

from __future__ import annotations

import pytest

from src.domains.security.tools.cvss_tool import calculate_cvss, save_cvss_assessment
from src.domains.security.tools.security_artifact_tool import check_password_policy, save_security_artifact


# ── CVSS determinístico ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "vector,base_score,severity",
    [
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8, "Critical"),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0, "None"),
        ("CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", 1.8, "Low"),
    ],
)
def test_calculate_cvss_is_deterministic(vector, base_score, severity):
    out = calculate_cvss(vector)
    assert out["base_score"] == base_score and out["severity"] == severity


def test_calculate_cvss_incomplete_vector():
    out = calculate_cvss("CVSS:3.1/AV:N")
    assert out["error"] == "vetor_incompleto" and "AC" in out["missing_metrics"]


async def test_save_cvss_rejects_incomplete_vector_before_store():
    # vetor incompleto → erro ANTES de tocar o store (store=None prova isso).
    out = await save_cvss_assessment(None, vector="CVSS:3.1/AV:N")  # type: ignore[arg-type]
    assert out["error"] == "vetor_incompleto"


# ── Política de senha determinística (NIST 800-63B) ───────────────────────────
def test_check_password_policy_flags_weak():
    out = check_password_policy({"min_length": 6})
    assert out["compliant"] is False
    issues = {f["issue"] for f in out["findings"]}
    assert any("Comprimento" in i for i in issues)
    assert any("MFA" in i for i in issues)


def test_check_password_policy_strong_is_compliant():
    out = check_password_policy(
        {"min_length": 14, "mfa": True, "check_breached_passwords": True, "rate_limit_login": True}
    )
    assert out["compliant"] is True


# ── Guards de validação (retornam antes do store) ─────────────────────────────
async def test_save_security_artifact_rejects_invalid_kind_before_store():
    out = await save_security_artifact(None, kind="nope", target="t")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
