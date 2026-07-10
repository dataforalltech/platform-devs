"""Testes das tools do security-mcp-server.

Foco: a saída deve ser DERIVADA DOS INPUTS (nada de listas fixas/constantes).
Cada teste passa inputs variados e afirma que a análise reflete o que foi
recebido (código, manifest, vetor CVSS, contexto de compliance, políticas).
Cobre também os helpers puros (_mask, _cvss_roundup, _severity_rating).
"""

from __future__ import annotations

from src.tools.security_tools import (
    _cvss_roundup,
    _mask,
    _severity_rating,
    analyze_compliance,
    calculate_cvss,
    check_password_policy,
    generate_incident_response_plan,
    generate_security_controls,
    generate_threat_model,
    harden_headers,
    map_attack_surface,
    review_secure_code,
    scan_dependency_risks,
    scan_secrets,
    stub_tool,
)


# ── review_secure_code ──────────────────────────────────────────────────────── #
def test_review_code_flags_multiple_severities_and_sorts():
    code = "\n".join(
        [
            "import hashlib",
            "hashlib.md5(data)",  # medium — hash fraco
            "token = random.random()",  # low — PRNG
            'query = "SELECT * FROM t WHERE x=" + inp',  # high — SQLi
            'os.system("ls " + request.path)',  # critical — cmd injection
        ]
    )
    result = review_secure_code(code=code, language="python")
    assert result["lines_scanned"] == 5
    assert result["issues_found"] >= 4
    counts = result["severity_counts"]
    assert counts["critical"] >= 1
    assert counts["high"] >= 1
    assert counts["medium"] >= 1
    assert counts["low"] >= 1
    # Ordenado por severidade: o primeiro é critical.
    assert result["issues"][0]["severity"] == "critical"
    # Linha reportada é derivada da posição real no código.
    cmd = next(i for i in result["issues"] if i["severity"] == "critical")
    assert cmd["line"] == 5
    assert cmd["cwe"] == "CWE-78"
    assert result["verdict"] == "reprovado"


def test_review_code_low_only_yields_atencao():
    result = review_secure_code(code="x = random.random()", language="python")
    assert result["issues_found"] == 1
    assert result["severity_counts"]["low"] == 1
    assert result["verdict"] == "atenção"


def test_review_code_clean_is_aprovado():
    result = review_secure_code(code="x = 1 + 2\ny = x * 3", language="python")
    assert result["issues_found"] == 0
    assert result["verdict"] == "aprovado"
    assert result["severity_counts"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}


def test_review_code_language_filter_skips_non_matching_patterns():
    # innerHTML/XSS só se aplica a js/ts; em python o padrão é ignorado (continue).
    py = review_secure_code(code="el.innerHTML = userInput", language="python")
    assert py["issues_found"] == 0
    # Mesmo código em javascript dispara o XSS (high).
    js = review_secure_code(code="el.innerHTML = userInput", language="javascript")
    assert js["issues_found"] == 1
    assert js["issues"][0]["cwe"] == "CWE-79"
    assert js["verdict"] == "reprovado"


# ── scan_secrets ────────────────────────────────────────────────────────────── #
def test_scan_secrets_detects_critical_aws_key_and_masks():
    result = scan_secrets(content="key = AKIAIOSFODNN7EXAMPLE", filename="config.py")
    assert result["filename"] == "config.py"
    assert result["secrets_found"] == 1
    finding = result["findings"][0]
    assert finding["type"] == "AWS Access Key ID"
    assert finding["severity"] == "critical"
    assert finding["cwe"] == "CWE-798"
    # Valor mascarado, nunca em claro.
    assert "AKIAIOSFODNN7EXAMPLE" not in finding["masked_value"]
    assert "…" in finding["masked_value"]
    assert result["status"] == "critical"


def test_scan_secrets_high_only_status_findings():
    # Token construído em runtime (split) p/ NÃO casar o push-protection do GitHub;
    # o scan_secrets recebe a string completa e detecta o padrão xoxb- normalmente.
    slack = "xoxb-" + "1234567890" + "-abcdefghijklmnop"
    result = scan_secrets(content=f"slack = {slack}")
    assert result["filename"] == "(inline)"
    assert result["secrets_found"] >= 1
    assert all(f["severity"] != "critical" for f in result["findings"])
    assert result["status"] == "findings"


def test_scan_secrets_short_captured_value_fully_masked():
    # 'secret' (6 chars) é capturado pelo padrão de credencial hardcoded → '****'.
    result = scan_secrets(content='password = "secret"')
    assert result["secrets_found"] >= 1
    masked = {f["masked_value"] for f in result["findings"]}
    assert "****" in masked


def test_scan_secrets_clean_content():
    result = scan_secrets(content="just some ordinary text\nno secrets here")
    assert result["secrets_found"] == 0
    assert result["status"] == "clean"
    assert result["lines_scanned"] == 2


# ── calculate_cvss ──────────────────────────────────────────────────────────── #
def test_cvss_critical_scope_unchanged():
    result = calculate_cvss(vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
    assert result["base_score"] == 9.8
    assert result["severity"] == "Critical"
    assert result["metrics"]["S"] == "U"
    assert result["status"] == "calculated"


def test_cvss_scope_changed_path():
    result = calculate_cvss(vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H")
    assert result["base_score"] == 10.0
    assert result["severity"] == "Critical"


def test_cvss_zero_impact_is_none_severity():
    result = calculate_cvss(vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N")
    assert result["base_score"] == 0.0
    assert result["severity"] == "None"


def test_cvss_incomplete_vector_reports_missing():
    result = calculate_cvss(vector="CVSS:3.1/AV:N/AC:L")
    assert result["error"] == "vetor_incompleto"
    assert set(result["missing_metrics"]) == {"PR", "UI", "S", "C", "I", "A"}


def test_cvss_invalid_metric_value():
    result = calculate_cvss(vector="CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
    assert result["error"] == "valor_de_metrica_invalido"


# ── helpers puros ───────────────────────────────────────────────────────────── #
def test_mask_short_and_long_values():
    assert _mask("short") == "****"
    assert _mask("        ") == "****"  # strip → vazio
    long_masked = _mask("abcdefghijklmnop")
    assert long_masked.startswith("abc")
    assert long_masked.endswith("(16 chars)")


def test_cvss_roundup_exact_and_rounded():
    assert _cvss_roundup(1.0) == 1.0  # múltiplo exato de 10000 → curto-circuito
    assert _cvss_roundup(0.123456) == 0.2  # arredonda para cima (0.1 step)


def test_severity_rating_all_bands():
    assert _severity_rating(0.0) == "None"
    assert _severity_rating(3.9) == "Low"
    assert _severity_rating(4.0) == "Medium"
    assert _severity_rating(6.9) == "Medium"
    assert _severity_rating(7.0) == "High"
    assert _severity_rating(8.9) == "High"
    assert _severity_rating(9.0) == "Critical"


# ── generate_threat_model ───────────────────────────────────────────────────── #
def test_threat_model_defaults_components():
    result = generate_threat_model(system="Billing")
    assert result["system"] == "Billing"
    assert result["title"] == "Threat Model: Billing"
    assert result["methodology"] == "STRIDE"
    # 4 componentes default × 6 categorias STRIDE.
    assert result["threat_count"] == 24
    assert result["scope"].startswith("Avaliação")


def test_threat_model_uses_custom_components_and_scope():
    result = generate_threat_model(system="IoT Hub", scope="somente ingestão", components=["Ingest Worker"])
    assert result["components"] == ["Ingest Worker"]
    assert result["threat_count"] == 6
    assert result["scope"] == "somente ingestão"
    assert all(t["component"] == "Ingest Worker" for t in result["threats"])
    # EoP e Information Disclosure são high por default.
    eop = next(t for t in result["threats"] if t["category"] == "Elevation of Privilege")
    assert eop["default_severity"] == "high"


# ── map_attack_surface ──────────────────────────────────────────────────────── #
def test_attack_surface_defaults():
    result = map_attack_surface(system="Portal")
    assert result["title"] == "Attack Surface: Portal"
    # Defaults incluem um endpoint 'optional' e uma integração 'public'.
    assert result["risk_hotspots"]["unauthenticated_endpoints"]
    assert result["risk_hotspots"]["public_integrations"]


def test_attack_surface_derives_hotspots_from_inputs():
    result = map_attack_surface(
        system="Ledger",
        endpoints=[
            {"type": "API", "path": "/secure", "authentication": "required"},
            {"type": "API", "path": "/open", "authentication": "none"},
        ],
        integrations=[
            {"name": "db", "type": "internal", "exposure": "none"},
            {"name": "partner", "type": "external", "exposure": "public"},
        ],
    )
    exposed = result["risk_hotspots"]["unauthenticated_endpoints"]
    assert [e["path"] for e in exposed] == ["/open"]
    public = result["risk_hotspots"]["public_integrations"]
    assert [i["name"] for i in public] == ["partner"]


# ── generate_security_controls ──────────────────────────────────────────────── #
def test_security_controls_defaults_full_catalog():
    result = generate_security_controls(system="Core")
    assert result["control_count"] == 8
    assert result["title"] == "Security Controls: Core"
    assert all(c["status"] == "recommended" for c in result["controls"])


def test_security_controls_custom_categories_with_unknown_fallback():
    result = generate_security_controls(system="Core", threat_categories=["authentication", "custom_control"])
    assert result["control_count"] == 2
    by_id = {c["id"]: c for c in result["controls"]}
    assert by_id["SC01"]["name"].startswith("Autenticação")
    # Chave desconhecida cai no fallback (usa a própria chave como nome).
    assert by_id["SC02"]["name"] == "custom_control"


# ── scan_dependency_risks ───────────────────────────────────────────────────── #
def test_scan_dependencies_parses_manifest_and_flags():
    manifest = "\n".join(
        [
            "# comentário deve ser ignorado",
            "",
            "fastapi==0.104.0",  # 0.x → flag pre-1.0
            "requests>=2.31.0",  # range aberto
            "leftpad v1.2.3",  # cai no segundo regex (fallback)
            "totally invalid line",  # não casa nenhum regex
            "numpy==1.26.0",
        ]
    )
    result = scan_dependency_risks(manifest=manifest, ecosystem="python")
    assert result["ecosystem"] == "python"
    assert result["dependencies_found"] == 4
    pkgs = {d["package"]: d for d in result["dependencies"]}
    assert set(pkgs) == {"fastapi", "requests", "leftpad", "numpy"}
    assert "pre-1.0" in pkgs["fastapi"]["flags"]
    assert pkgs["numpy"]["flags"] == "-"
    # >= conta como spec não fixado.
    assert result["hygiene"]["unpinned_or_range_specs"] >= 1


def test_scan_dependencies_empty_ecosystem_defaults_unknown():
    result = scan_dependency_risks(manifest="flask==2.0.1", ecosystem="")
    assert result["ecosystem"] == "unknown"
    assert result["dependencies_found"] == 1


# ── analyze_compliance ──────────────────────────────────────────────────────── #
def test_compliance_no_context_all_gaps_high_priority():
    result = analyze_compliance(framework="owasp")
    assert result["controls_total"] == 10
    assert result["controls_met"] == 0
    assert result["compliance_percentage"] == "0%"
    assert result["priority"] == "high"
    assert len(result["gaps"]) == 10


def test_compliance_partial_context_medium_priority():
    ctx = {"satisfied": ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08"]}
    result = analyze_compliance(framework="owasp", context=ctx)
    assert result["controls_met"] == 8
    assert result["compliance_percentage"] == "80%"
    assert result["priority"] == "medium"


def test_compliance_full_context_low_priority():
    ctx = {"satisfied": [f"A0{i}" if i < 10 else "A10" for i in range(1, 11)]}
    result = analyze_compliance(framework="owasp", context=ctx)
    assert result["compliance_percentage"] == "100%"
    assert result["priority"] == "low"
    assert result["gaps"] == []


def test_compliance_other_framework_by_name():
    result = analyze_compliance(framework="LGPD", context={"satisfied": ["base_legal"]})
    assert result["framework"].startswith("LGPD")
    assert result["controls_met"] == 1


def test_compliance_unknown_framework_errors():
    result = analyze_compliance(framework="hipaa-xyz")
    assert result["error"] == "framework_desconhecido"
    assert "owasp" in result["supported"]


# ── generate_incident_response_plan ─────────────────────────────────────────── #
def test_incident_plan_sla_by_severity():
    assert generate_incident_response_plan(severity="critical")["response_sla"] == "15 min"
    assert generate_incident_response_plan(severity="high")["response_sla"] == "1 h"
    assert generate_incident_response_plan(severity="medium")["response_sla"] == "4 h"
    assert generate_incident_response_plan(severity="low")["response_sla"] == "1 dia útil"
    # Severidade desconhecida cai no default de 1 h.
    assert generate_incident_response_plan(severity="weird")["response_sla"] == "1 h"


def test_incident_plan_reflects_incident_type_and_phases():
    result = generate_incident_response_plan(incident_type="ransomware", severity="critical")
    assert result["incident_type"] == "ransomware"
    assert result["framework"] == "NIST SP 800-61r2"
    assert set(result["phases"]) == {
        "1_preparation",
        "2_detection_analysis",
        "3_containment",
        "4_eradication",
        "5_recovery",
        "6_post_incident",
    }


# ── harden_headers ──────────────────────────────────────────────────────────── #
def test_harden_headers_none_all_missing():
    result = harden_headers()
    assert result["present_secure_headers"] == []
    assert result["score"] == "0/7"
    assert len(result["missing_headers"]) == 7
    assert result["info_leak_warnings"] == []


def test_harden_headers_detects_present_and_info_leak():
    result = harden_headers(
        current_headers={
            "Strict-Transport-Security": "max-age=100",
            "Server": "nginx/1.25",
            "X-Powered-By": "PHP/8.2",
        }
    )
    present = {h["header"] for h in result["present_secure_headers"]}
    assert "Strict-Transport-Security" in present
    assert result["score"] == "1/7"
    assert result["info_leak_warnings"]  # Server/X-Powered-By sinalizados


# ── check_password_policy ───────────────────────────────────────────────────── #
def test_password_policy_default_non_compliant():
    result = check_password_policy()
    assert result["standard"] == "NIST SP 800-63B"
    assert result["compliant"] is False
    severities = {f["severity"] for f in result["findings"]}
    assert "high" in severities  # min_length e MFA


def test_password_policy_strong_is_compliant():
    result = check_password_policy(
        policy={
            "min_length": 12,
            "mfa": True,
            "check_breached_passwords": True,
            "rate_limit_login": True,
        }
    )
    assert result["findings"] == []
    assert result["compliant"] is True


def test_password_policy_discouraged_rules_are_low_only():
    result = check_password_policy(
        policy={
            "min_length": 16,
            "mfa": True,
            "check_breached_passwords": True,
            "rate_limit_login": True,
            "require_complexity": True,
            "periodic_rotation": True,
        }
    )
    issues = {f["issue"] for f in result["findings"]}
    assert "Regras de complexidade obrigatórias" in issues
    assert "Rotação periódica forçada" in issues
    assert all(f["severity"] == "low" for f in result["findings"])
    assert result["compliant"] is True  # nenhum high/critical


# ── stub_tool (status) ──────────────────────────────────────────────────────── #
def test_stub_tool_status():
    result = stub_tool()
    assert result == {"status": "ok", "service": "security", "tools": 12}
