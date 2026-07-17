"""Unidade dos geradores determinísticos de segurança (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
um guard de spec inválida, mais um teste global de DETERMINISMO (mesma spec chamada 2x
→ output idêntico)."""

from __future__ import annotations

import pytest

from src.tools.generator_tool import (
    generate_api_security_spec,
    generate_compliance_report,
    generate_security_controls,
    generate_security_handbook,
)

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
CONTROLS_SPEC = {
    "framework": "nist_csf",
    "assets": ["api-gateway", "auth-db"],
    "controls": [
        {
            "key": "AC-2",
            "name": "Account Management",
            "category": "access_control",
            "applies_to": ["auth-db"],
        },
        {"control_key": "SC-8", "name": "Transmission Confidentiality"},
    ],
}
API_SPEC = {
    "title": "Payments API Security",
    "auth": {"type": "oauth2", "flow": "client_credentials"},
    "endpoints": [
        {"path": "/v1/pay", "method": "post", "auth_required": True, "scopes": ["pay:write"]},
        {"path": "/v1/health", "method": "get", "auth_required": False},
    ],
    "threats": ["broken_object_level_authorization", {"id": "T1", "description": "token replay"}],
}
COMPLIANCE_SPEC = {
    "standard": "SOC2",
    "findings": [
        {"control": "CC6.1", "status": "pass", "note": "MFA enforced"},
        {"control": "CC6.2", "status": "fail"},
        {"control": "CC7.1", "status": "na"},
    ],
}
HANDBOOK_SPEC = {
    "title": "Engineering Security Handbook",
    "sections": [
        {"title": "Secrets Management", "content": "Use the vault.", "items": ["rotate", "never commit"]},
        {"title": "Incident Response"},
    ],
}


# ── 1. Matriz de controles ────────────────────────────────────────────────────
def test_generate_security_controls_markers():
    out = generate_security_controls(CONTROLS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "security_controls"
    assert out["filename"] == "security-controls-matrix.md"
    assert "Security Controls Matrix — nist_csf" in art
    # colunas de assets (ordenadas) + cabeçalho da tabela
    assert "| api-gateway | auth-db |" in art
    assert "AC-2" in art and "SC-8" in art
    # AC-2 só se aplica a auth-db → "-" p/ api-gateway e "x" p/ auth-db
    ac2_row = next(line for line in art.splitlines() if line.startswith("| AC-2 "))
    assert ac2_row.endswith("| - | x |")
    # SC-8 sem applies_to → cobre todos os assets
    sc8_row = next(line for line in art.splitlines() if line.startswith("| SC-8 "))
    assert sc8_row.endswith("| x | x |")


def test_generate_security_controls_requires_controls():
    assert generate_security_controls({"framework": "cis", "controls": []})["error"] == "missing_controls"


# ── 2. Spec de segurança de API ────────────────────────────────────────────────
def test_generate_api_security_spec_markers():
    out = generate_api_security_spec(API_SPEC)
    art = out["artifact"]
    assert out["kind"] == "api_security_spec"
    assert out["filename"] == "api-security-spec.yaml"
    assert 'title: "Payments API Security"' in art
    assert 'type: "oauth2"' in art
    assert 'path: "/v1/pay"' in art
    assert 'method: "POST"' in art  # normalizado p/ maiúsculas
    assert "auth_required: true" in art and "auth_required: false" in art
    assert "scopes:" in art and "pay:write" in art
    assert "threats:" in art
    assert "baseline_controls:" in art and "enforce_tls" in art


def test_generate_api_security_spec_requires_endpoints():
    assert generate_api_security_spec({"endpoints": []})["error"] == "missing_endpoints"


# ── 3. Relatório de compliance ─────────────────────────────────────────────────
def test_generate_compliance_report_markers():
    out = generate_compliance_report(COMPLIANCE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "compliance_report"
    assert out["filename"] == "compliance-report.md"
    assert "SOC2 Compliance Report" in art
    # 1 pass de 2 avaliados (na excluído do denominador) → 50.0%
    assert "Compliance score: 50.0%" in art
    assert "CC6.1" in art and "CC6.2" in art and "CC7.1" in art
    assert "MFA enforced" in art
    # sumário por status
    assert "| pass | 1 |" in art and "| fail | 1 |" in art and "| na | 1 |" in art


def test_generate_compliance_report_requires_findings():
    assert generate_compliance_report({"standard": "LGPD", "findings": []})["error"] == "missing_findings"


# ── 4. Handbook de segurança ───────────────────────────────────────────────────
def test_generate_security_handbook_markers():
    out = generate_security_handbook(HANDBOOK_SPEC)
    art = out["artifact"]
    assert out["kind"] == "security_handbook"
    assert out["filename"] == "security-handbook.md"
    assert "# Engineering Security Handbook" in art
    assert "## Table of Contents" in art
    assert "[Secrets Management](#secrets-management)" in art
    assert "## Incident Response" in art
    assert "- rotate" in art
    # seção sem conteúdo/itens vira placeholder
    assert "_TODO: conteúdo desta seção._" in art


def test_generate_security_handbook_requires_sections():
    assert generate_security_handbook({"sections": []})["error"] == "missing_sections"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_security_controls, CONTROLS_SPEC),
        (generate_api_security_spec, API_SPEC),
        (generate_compliance_report, COMPLIANCE_SPEC),
        (generate_security_handbook, HANDBOOK_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))


def test_auth_key_ordering_is_stable_regardless_of_input_order():
    # dicts de auth com mesma composição mas ordens de inserção diferentes → mesmo output.
    base = {"endpoints": [{"path": "/x"}]}
    a = generate_api_security_spec({**base, "auth": {"type": "oauth2", "flow": "cc"}})
    b = generate_api_security_spec({**base, "auth": {"flow": "cc", "type": "oauth2"}})
    assert a == b


def test_api_security_spec_yaml_valid_with_backslash():
    # Regressão: valores com barra invertida (paths Windows, regex) devem gerar YAML
    # válido — _yaml_scalar escapa a barra ANTES de aspar (senão \c/\d são escapes inválidos).
    import yaml

    out = generate_api_security_spec(
        {
            "endpoints": [{"path": "/x", "method": "GET"}],
            "auth": {"type": "jwt", "issuer": "C:\certs\ca"},
            "threats": [{"name": "injection", "pattern": "matches \d+"}],
            "title": "API \ Sec",
        }
    )
    parsed = yaml.safe_load(out["artifact"])  # não deve levantar ScannerError
    assert isinstance(parsed, dict)
    assert parsed["auth"]["issuer"] == "C:\certs\ca"
