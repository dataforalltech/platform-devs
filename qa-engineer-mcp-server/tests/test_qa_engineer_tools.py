"""Testes das tools do qa-engineer-mcp-server.

Foco: a saída deve ser DERIVADA DOS INPUTS. Cada teste passa inputs custom e
afirma que eles reaparecem na saída, e cobre os ramos condicionais de cada tool
(defaults vs valores fornecidos, thresholds de severidade, gaps de cobertura,
frameworks/linguagens alternativos). Sem I/O de rede — as tools são puras; os
defaults dependentes de env (base_url) são fixados via monkeypatch.delenv.
"""

from __future__ import annotations

from src.tools.qa_engineer_tools import (
    analyze_quality_requirement,
    classify_bug_severity,
    generate_api_tests,
    generate_bug_report,
    generate_cypress_tests,
    generate_e2e_tests,
    generate_gherkin_scenarios,
    generate_k6_performance_test,
    generate_playwright_tests,
    generate_postman_collection,
    generate_quality_gate,
    generate_regression_suite,
    generate_smoke_test_suite,
    generate_test_cases,
    generate_test_plan,
    generate_uat_checklist,
    generate_unit_tests,
    review_test_coverage,
    validate_story_testability,
)


# ── analyze_quality_requirement ─────────────────────────────────────────────── #
def test_analyze_requirement_echoes_input_and_default_context():
    result = analyze_quality_requirement("Login deve responder em <2s")
    assert result["requirement"] == "Login deve responder em <2s"
    assert result["context"] == {}  # default quando não fornecido
    assert "performance" in result["quality_dimensions"]
    assert result["automation_feasibility"] == "high"


def test_analyze_requirement_preserves_custom_context():
    ctx = {"module": "billing", "sla": "99.9%"}
    result = analyze_quality_requirement("Faturas corretas", context=ctx)
    assert result["context"] == ctx


# ── generate_test_plan ──────────────────────────────────────────────────────── #
def test_test_plan_derives_title_and_scope_from_inputs():
    result = generate_test_plan("Checkout", scope="partial", team="Squad Pagamentos")
    assert result["title"] == "Plano de Teste — Checkout"
    assert result["scope"] == "partial"
    assert result["team"] == "Squad Pagamentos"
    assert any("Checkout" in obj for obj in result["objectives"])
    assert set(result["test_levels"]) == {"unit", "integration", "e2e", "api"}


def test_test_plan_defaults_scope_full_and_team_none():
    result = generate_test_plan("Relatórios")
    assert result["scope"] == "full"
    assert result["team"] is None


# ── generate_test_cases ─────────────────────────────────────────────────────── #
def test_test_cases_count_and_type_derive_from_input():
    result = generate_test_cases("Busca", test_type="integration", count=3)
    assert result["feature"] == "Busca"
    assert result["test_type"] == "integration"
    assert result["total"] == 3
    assert len(result["cases"]) == 3
    ids = [c["id"] for c in result["cases"]]
    assert ids == ["TC-001", "TC-002", "TC-003"]
    # o primeiro caso é high priority; os demais medium.
    assert result["cases"][0]["priority"] == "high"
    assert result["cases"][1]["priority"] == "medium"
    # todos os casos carregam o feature na descrição (derivado do input).
    assert all("Busca" in c["title"] for c in result["cases"])
    assert all(c["type"] == "integration" for c in result["cases"])


def test_test_cases_default_type_and_count():
    result = generate_test_cases("Perfil")
    assert result["test_type"] == "functional"
    assert result["total"] == 5
    assert len(result["cases"]) == 5


# ── generate_gherkin_scenarios ──────────────────────────────────────────────── #
def test_gherkin_uses_custom_scenarios_and_feature():
    result = generate_gherkin_scenarios("Reembolso", scenarios=["aprova reembolso", "nega reembolso"])
    assert result["feature"] == "Reembolso"
    assert "Feature: Reembolso" in result["feature_block"]
    names = [s["name"] for s in result["scenarios"]]
    assert names == ["Aprova Reembolso", "Nega Reembolso"]
    # feature aparece dentro do gherkin gerado.
    assert "'Reembolso'" in result["scenarios"][0]["gherkin"]
    # primeiro cenário é @smoke; os demais @regression.
    assert result["scenarios"][0]["tags"] == ["@smoke"]
    assert result["scenarios"][1]["tags"] == ["@regression"]


def test_gherkin_default_scenarios_when_none():
    result = generate_gherkin_scenarios("Cadastro")
    assert len(result["scenarios"]) == 3  # três cenários default
    assert result["scenarios"][0]["id"] == "SCN-001"


# ── generate_e2e_tests / playwright / cypress ───────────────────────────────── #
def test_e2e_playwright_embeds_feature_and_explicit_base_url():
    result = generate_e2e_tests("Dashboard", framework="playwright", base_url="http://app.local")
    assert result["framework"] == "playwright"
    assert result["base_url"] == "http://app.local"
    assert "test.describe('Dashboard'" in result["code"]
    assert "http://app.local" in result["code"]


def test_e2e_cypress_branch_differs_from_playwright():
    result = generate_e2e_tests("Carrinho", framework="cypress", base_url="http://shop.local")
    assert result["framework"] == "cypress"
    # cypress usa cy.login/cy.visit — não a API de @playwright/test.
    assert "cy.login" in result["code"]
    assert "@playwright/test" not in result["code"]


def test_e2e_base_url_falls_back_to_default_when_env_absent(monkeypatch):
    monkeypatch.delenv("TEST_APP_URL", raising=False)
    result = generate_e2e_tests("Home")
    assert result["base_url"] == "http://localhost:3000"


def test_e2e_base_url_reads_env(monkeypatch):
    monkeypatch.setenv("TEST_APP_URL", "http://env.example")
    result = generate_e2e_tests("Home")
    assert result["base_url"] == "http://env.example"


def test_playwright_wrapper_delegates_to_e2e():
    result = generate_playwright_tests("Login", base_url="http://p.local")
    assert result["framework"] == "playwright"
    assert result["base_url"] == "http://p.local"
    assert "test.describe('Login'" in result["code"]


def test_cypress_wrapper_delegates_to_e2e():
    result = generate_cypress_tests("Logout", base_url="http://c.local")
    assert result["framework"] == "cypress"
    assert "cy.login" in result["code"]


# ── generate_api_tests ──────────────────────────────────────────────────────── #
def test_api_tests_derive_class_name_from_method_and_endpoint():
    result = generate_api_tests("/users/me", method="POST", base_url="http://api.local")
    assert result["endpoint"] == "/users/me"
    assert result["method"] == "POST"
    assert result["base_url"] == "http://api.local"
    # classe derivada: Test<Method.title><endpoint sem barras>.title()
    assert "class TestPostUsersme" in result["pytest_code"]
    assert 'BASE_URL = "http://api.local"' in result["pytest_code"]
    # método http em minúsculas no corpo.
    assert "httpx.post(" in result["pytest_code"]


def test_api_tests_default_method_and_env_base_url(monkeypatch):
    monkeypatch.delenv("TEST_API_URL", raising=False)
    result = generate_api_tests("/health")
    assert result["method"] == "GET"
    assert result["base_url"] == "http://localhost:8000"
    assert "httpx.get(" in result["pytest_code"]


# ── generate_unit_tests ─────────────────────────────────────────────────────── #
def test_unit_tests_python_branch_embeds_module():
    result = generate_unit_tests("app.services.billing", language="python")
    assert result["language"] == "python"
    assert "from app.services.billing import YourClass" in result["code"]
    assert "import pytest" in result["code"]


def test_unit_tests_typescript_branch():
    result = generate_unit_tests("orders", language="typescript")
    assert result["language"] == "typescript"
    assert "from 'vitest'" in result["code"]
    assert "./orders" in result["code"]


def test_unit_tests_defaults_to_python():
    result = generate_unit_tests("mod")
    assert result["language"] == "python"


# ── generate_postman_collection ─────────────────────────────────────────────── #
def test_postman_uses_custom_name_and_endpoints():
    result = generate_postman_collection(
        "Billing API", base_url="http://api.local", endpoints=["/invoices", "/payments"]
    )
    assert result["info"]["name"] == "Billing API"
    assert len(result["item"]) == 2
    names = [it["name"] for it in result["item"]]
    assert names == ["GET /invoices", "GET /payments"]
    assert result["item"][0]["request"]["url"]["raw"] == "http://api.local/invoices"


def test_postman_default_endpoints_and_env_base_url(monkeypatch):
    monkeypatch.delenv("TEST_API_URL", raising=False)
    result = generate_postman_collection("Svc")
    assert len(result["item"]) == 2  # endpoints default
    assert result["item"][0]["request"]["url"]["raw"] == "http://localhost:8000/health"


# ── classify_bug_severity — todos os limiares P1..P4 ────────────────────────── #
def test_classify_p1_critical_always():
    result = classify_bug_severity("data loss", impact="critical", frequency="always")
    assert result["score"] == 16
    assert result["severity"] == "P1"
    assert result["sla"] == "4h"
    assert "Hotfix" in result["recommended_action"]


def test_classify_p2_medium_often():
    result = classify_bug_severity("slow page", impact="medium", frequency="often")
    assert result["score"] == 6
    assert result["severity"] == "P2"
    assert result["sla"] == "24h"


def test_classify_p3_medium_sometimes():
    result = classify_bug_severity("cosmetic", impact="medium", frequency="sometimes")
    assert result["score"] == 4
    assert result["severity"] == "P3"
    assert result["sla"] == "72h"


def test_classify_p4_low_rarely():
    result = classify_bug_severity("typo", impact="low", frequency="rarely")
    assert result["score"] == 1
    assert result["severity"] == "P4"
    assert result["sla"] == "backlog"


def test_classify_unknown_values_fall_back_to_medium_weights():
    # impact/frequency desconhecidos → peso 2 cada → score 4 → P3.
    result = classify_bug_severity("weird", impact="???", frequency="???")
    assert result["score"] == 4
    assert result["severity"] == "P3"


# ── generate_bug_report ─────────────────────────────────────────────────────── #
def test_bug_report_uses_custom_steps_and_severity():
    result = generate_bug_report("Botão não clica", steps=["abrir", "clicar"], severity="P1")
    assert result["title"] == "Botão não clica"
    assert result["severity"] == "P1"
    assert result["steps_to_reproduce"] == ["abrir", "clicar"]
    assert result["labels"] == ["bug", "p1"]  # severity minúscula no label


def test_bug_report_defaults_steps_and_severity():
    result = generate_bug_report("Erro genérico")
    assert result["severity"] == "P2"
    assert result["labels"] == ["bug", "p2"]
    assert len(result["steps_to_reproduce"]) == 3  # passos default


# ── validate_story_testability ──────────────────────────────────────────────── #
def test_story_testable_with_criteria_and_long_text():
    story = "Como usuário quero exportar relatórios em PDF para arquivar"
    result = validate_story_testability(story, acceptance_criteria=["gera PDF", "download inicia"])
    assert result["story"] == story
    assert result["issues"] == []
    assert result["testability_score"] == 100
    assert result["is_testable"] is True
    assert result["suggestions"] == []
    assert result["acceptance_criteria_count"] == 2


def test_story_not_testable_short_and_no_criteria():
    result = validate_story_testability("curto")
    # duas issues: sem critérios + story vaga → score 100 - 2*25 = 50.
    assert "Critérios de aceite não definidos" in result["issues"]
    assert any("vaga" in i for i in result["issues"])
    assert result["testability_score"] == 50
    assert result["is_testable"] is False
    assert result["suggestions"]  # não vazio quando há issues


def test_story_single_issue_scores_75_and_is_testable():
    # story longa (>=20 chars) mas sem critérios → 1 issue → score 75 → testável.
    story = "Como admin quero desativar usuários inativos automaticamente"
    result = validate_story_testability(story)
    assert result["issues"] == ["Critérios de aceite não definidos"]
    assert result["testability_score"] == 75
    assert result["is_testable"] is True


# ── generate_quality_gate ───────────────────────────────────────────────────── #
def test_quality_gate_default_thresholds_and_operators():
    result = generate_quality_gate("payments-api")
    assert result["service"] == "payments-api"
    assert result["blocking"] is True
    gates = {g["name"]: g for g in result["gates"]}
    # coverage/rate usam '>='; os demais '<='.
    assert gates["unit_test_coverage"]["operator"] == ">="
    assert gates["integration_test_pass_rate"]["operator"] == ">="
    assert gates["performance_p95_ms"]["operator"] == "<="
    assert gates["code_duplication_percent"]["operator"] == "<="
    assert "payments-api" in result["ci_config"]


def test_quality_gate_custom_thresholds_override_defaults():
    # NB: o ci_config referencia as 4 chaves canônicas (unit_test_coverage,
    # e2e_critical_pass_rate, performance_p95_ms, security_vulnerabilities_critical);
    # um dict PARCIAL quebra com KeyError — ver test_quality_gate_partial_thresholds_raises.
    custom = {
        "unit_test_coverage": 95,
        "integration_test_pass_rate": 100,
        "e2e_critical_pass_rate": 100,
        "performance_p95_ms": 300,
        "security_vulnerabilities_critical": 0,
        "security_vulnerabilities_high": 0,
        "code_duplication_percent": 3,
    }
    result = generate_quality_gate("svc", thresholds=custom)
    gates = {g["name"]: g for g in result["gates"]}
    assert gates["unit_test_coverage"]["threshold"] == 95
    assert gates["performance_p95_ms"]["threshold"] == 300
    assert gates["code_duplication_percent"]["threshold"] == 3
    assert "95%" in result["ci_config"]


def test_quality_gate_partial_thresholds_raises():
    # BUG PINNADO (produção): com thresholds parcial, o template ci_config referencia
    # chaves ausentes → KeyError. Documentado aqui p/ não regredir silenciosamente.
    import pytest

    with pytest.raises(KeyError):
        generate_quality_gate("svc", thresholds={"unit_test_coverage": 95})


# ── generate_uat_checklist ──────────────────────────────────────────────────── #
def test_uat_checklist_uses_custom_stakeholders():
    result = generate_uat_checklist("Onboarding", stakeholders=["CEO", "Suporte"])
    assert result["feature"] == "Onboarding"
    assert result["stakeholders"] == ["CEO", "Suporte"]
    assert result["sign_off_required"] == ["CEO", "Suporte"]
    assert len(result["checklist"]) == 8


def test_uat_checklist_default_stakeholders():
    result = generate_uat_checklist("Busca")
    assert result["stakeholders"] == ["Product Owner", "End User", "QA"]
    assert result["sign_off_required"] == ["Product Owner"]


# ── review_test_coverage ────────────────────────────────────────────────────── #
def test_review_coverage_with_gap():
    result = review_test_coverage("auth", current_coverage=55.0)
    assert result["current_coverage"] == 55.0
    assert result["target_coverage"] == 80.0
    assert result["gap"] == 25.0
    assert result["status"].startswith("⚠️")
    assert result["untested_areas"]  # não vazio quando há gap
    assert any("restantes" in r for r in result["recommendations"])


def test_review_coverage_target_reached_no_gap():
    result = review_test_coverage("auth", current_coverage=85.0)
    assert result["gap"] == 0
    assert result["status"] == "✅ OK"
    assert result["untested_areas"] == []
    assert result["recommendations"] == ["Cobertura atingida — manter qualidade"]


def test_review_coverage_defaults_to_zero():
    result = review_test_coverage("core")
    assert result["current_coverage"] == 0.0
    assert result["gap"] == 80.0


# ── generate_k6_performance_test ────────────────────────────────────────────── #
def test_k6_derives_vus_duration_and_endpoint():
    result = generate_k6_performance_test("http://api.local/x", vus=50, duration="1m")
    assert result["endpoint"] == "http://api.local/x"
    assert result["vus"] == 50
    assert result["duration"] == "1m"
    assert "vus: 50" in result["script"]
    assert "duration: '1m'" in result["script"]
    assert "http.get('http://api.local/x')" in result["script"]
    assert result["thresholds"] == {"p95_ms": 500, "error_rate": 0.01}


def test_k6_defaults():
    result = generate_k6_performance_test("http://api.local/y")
    assert result["vus"] == 10
    assert result["duration"] == "30s"


# ── generate_regression_suite ───────────────────────────────────────────────── #
def test_regression_suite_custom_cases_and_priority_split():
    result = generate_regression_suite("orders", test_cases=["a", "b", "c", "d"])
    assert result["service"] == "orders"
    assert result["suite_name"] == "Regression Suite — orders"
    assert result["total_cases"] == 4
    # dois primeiros (i<3) são critical; os demais high.
    assert result["cases"][0]["priority"] == "critical"
    assert result["cases"][1]["priority"] == "critical"
    assert result["cases"][2]["priority"] == "high"
    assert result["cases"][0]["id"] == "REG-001"
    assert result["estimated_time"] == "8 minutos"  # 4 * 2


def test_regression_suite_default_cases():
    result = generate_regression_suite("svc")
    assert result["total_cases"] == 6  # seis casos default


# ── generate_smoke_test_suite ───────────────────────────────────────────────── #
def test_smoke_suite_custom_endpoints():
    result = generate_smoke_test_suite("gateway", endpoints=["/ping", "/ready"])
    assert result["service"] == "gateway"
    assert result["suite_name"] == "Smoke Test Suite — gateway"
    endpoints = [t["endpoint"] for t in result["tests"]]
    assert endpoints == ["/ping", "/ready"]
    assert all(t["expected_status"] == 200 for t in result["tests"])


def test_smoke_suite_default_endpoints():
    result = generate_smoke_test_suite("svc")
    endpoints = [t["endpoint"] for t in result["tests"]]
    assert endpoints == ["/health", "/api/v1/status"]
