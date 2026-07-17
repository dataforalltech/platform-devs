"""Unidade dos geradores determinísticos de QA (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
mais um guard de spec inválida, mais um teste global de DETERMINISMO (mesma spec
chamada 2x → output idêntico)."""

from __future__ import annotations

import pytest

from src.tools.generator_tool import (
    generate_api_tests,
    generate_cypress_tests,
    generate_e2e_tests,
    generate_gherkin_scenarios,
    generate_k6_performance_test,
    generate_playwright_tests,
    generate_quality_gate,
    generate_regression_suite,
    generate_smoke_test_suite,
    generate_uat_checklist,
    generate_unit_tests,
)

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
GHERKIN_SPEC = {
    "feature": "User Login",
    "scenarios": [
        {
            "name": "Successful login",
            "given": "the user is on the login page",
            "when": ["fills the email", "fills the password"],
            "then": "is redirected to the dashboard",
        },
        {"name": "Missing password"},
    ],
}
UNIT_PYTEST_SPEC = {
    "framework": "pytest",
    "target": "billing.calculator",
    "cases": [
        {"name": "computes tax", "description": "verifica o cálculo de imposto"},
        {"name": "handles zero"},
    ],
}
UNIT_JEST_SPEC = {
    "framework": "jest",
    "target": "Cart",
    "cases": [{"name": "adds item"}],
}
E2E_PLAYWRIGHT_SPEC = {
    "framework": "playwright",
    "suite": "checkout",
    "flows": [
        {
            "name": "happy path",
            "steps": [{"type": "goto", "value": "/cart"}, {"type": "click", "selector": "#pay"}],
        },
    ],
}
E2E_CYPRESS_SPEC = {
    "framework": "cypress",
    "suite": "checkout",
    "flows": [{"name": "happy path", "steps": [{"type": "visit", "value": "/cart"}]}],
}
API_SPEC = {
    "base": "https://api.example.com",
    "endpoints": [
        {"method": "GET", "path": "/health", "expected_status": 200, "name": "health"},
        {"method": "POST", "path": "/orders", "status": 201},
    ],
}
PLAYWRIGHT_SPEC = {
    "suite": "login flow",
    "pages": [{"name": "login", "url": "/login"}],
    "actions": [
        {"type": "fill", "selector": "#email", "value": "a@b.com"},
        {"type": "click", "selector": "#submit"},
        {"type": "expect_text", "selector": ".welcome", "value": "Hi"},
    ],
}
CYPRESS_SPEC = {
    "suite": "login flow",
    "pages": ["/login"],
    "actions": [{"type": "type", "selector": "#email", "value": "a@b.com"}],
}
K6_SPEC = {
    "target": "https://api.example.com/health",
    "vus": 25,
    "duration": "1m",
    "thresholds": {"http_req_duration": ["p(95)<400"], "http_req_failed": "rate<0.02"},
}
REGRESSION_SPEC = {
    "name": "nightly",
    "modules": [
        {"name": "auth", "priority": "high", "cases": [{"name": "login"}, "logout"]},
        "billing",
    ],
}
SMOKE_SPEC = {
    "endpoints": [{"method": "get", "path": "/health", "expected_status": 200}],
    "pages": [{"url": "/"}],
}
UAT_SPEC = {
    "feature": "Checkout",
    "acceptance_criteria": [
        {"id": "AC-1", "description": "usuário consegue finalizar a compra"},
        "recibo é enviado por e-mail",
    ],
}
QUALITY_GATE_SPEC = {
    "service": "orders-api",
    "metrics": {"coverage": 80, "lint": "0 errors", "tests": {"min_pass_rate": 100}},
}


# ── 1. Gherkin ────────────────────────────────────────────────────────────────
def test_generate_gherkin_scenarios_markers():
    out = generate_gherkin_scenarios(GHERKIN_SPEC)
    art = out["artifact"]
    assert out["kind"] == "gherkin"
    assert out["filename"] == "user_login.feature"
    assert "Feature: User Login" in art
    assert "Scenario: Successful login" in art
    assert "Given the user is on the login page" in art
    assert "When fills the email" in art
    assert "And fills the password" in art  # 2º passo vira And
    assert "Then is redirected to the dashboard" in art
    assert "<given>" in art  # cenário sem passos → placeholder


def test_generate_gherkin_requires_scenarios():
    assert generate_gherkin_scenarios({"feature": "X", "scenarios": []})["error"] == "missing_scenarios"


# ── 2. Unit tests ─────────────────────────────────────────────────────────────
def test_generate_unit_tests_pytest_markers():
    out = generate_unit_tests(UNIT_PYTEST_SPEC)
    art = out["artifact"]
    assert out["kind"] == "unit_tests"
    assert out["filename"] == "test_billing_calculator.py"
    assert "def test_computes_tax():" in art
    assert "def test_handles_zero():" in art
    assert "# verifica o cálculo de imposto" in art
    assert "assert True" in art


def test_generate_unit_tests_jest_markers():
    out = generate_unit_tests(UNIT_JEST_SPEC)
    art = out["artifact"]
    assert out["filename"] == "cart.test.js"
    assert "describe('Cart'" in art
    assert "test('adds item'" in art
    assert "expect(true).toBe(true)" in art


def test_generate_unit_tests_rejects_unsupported_framework():
    assert generate_unit_tests({"framework": "mocha", "target": "x"})["error"] == "unsupported_framework"


# ── 3. E2E ────────────────────────────────────────────────────────────────────
def test_generate_e2e_tests_playwright_markers():
    out = generate_e2e_tests(E2E_PLAYWRIGHT_SPEC)
    art = out["artifact"]
    assert out["kind"] == "e2e_tests"
    assert "@playwright/test" in art
    assert "test.describe('checkout'" in art
    assert "await page.goto('/cart');" in art
    assert "await page.click('#pay');" in art


def test_generate_e2e_tests_cypress_markers():
    out = generate_e2e_tests(E2E_CYPRESS_SPEC)
    art = out["artifact"]
    assert "describe('checkout'" in art
    assert "cy.visit('/cart');" in art


def test_generate_e2e_requires_flows():
    assert generate_e2e_tests({"framework": "cypress", "flows": []})["error"] == "missing_flows"


# ── 4. API tests ──────────────────────────────────────────────────────────────
def test_generate_api_tests_markers():
    out = generate_api_tests(API_SPEC)
    art = out["artifact"]
    assert out["kind"] == "api_tests"
    assert out["filename"] == "test_api.py"
    assert 'BASE_URL = "https://api.example.com"' in art
    assert "def test_health():" in art
    assert 'requests.get(f"{BASE_URL}/health")' in art
    assert "assert resp.status_code == 200" in art
    assert "assert resp.status_code == 201" in art  # status usado quando expected_status ausente


def test_generate_api_tests_requires_endpoints():
    assert generate_api_tests({"base": "http://x", "endpoints": []})["error"] == "missing_endpoints"


# ── 5. Playwright ─────────────────────────────────────────────────────────────
def test_generate_playwright_tests_markers():
    out = generate_playwright_tests(PLAYWRIGHT_SPEC)
    art = out["artifact"]
    assert out["kind"] == "playwright"
    assert out["filename"] == "login_flow.spec.ts"
    assert "await page.goto('/login');" in art
    assert "await page.fill('#email', 'a@b.com');" in art
    assert "await page.click('#submit');" in art
    assert "toHaveText('Hi')" in art


def test_generate_playwright_defaults_without_pages():
    out = generate_playwright_tests({})
    art = out["artifact"]
    assert out["kind"] == "playwright"
    assert "await page.goto('/');" in art  # página default


# ── 6. Cypress ────────────────────────────────────────────────────────────────
def test_generate_cypress_tests_markers():
    out = generate_cypress_tests(CYPRESS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "cypress"
    assert out["filename"] == "login_flow.cy.js"
    assert "cy.visit('/login');" in art
    assert "cy.get('#email').type('a@b.com');" in art


def test_generate_cypress_defaults_without_pages():
    out = generate_cypress_tests({})
    assert "cy.visit('/');" in out["artifact"]


# ── 7. k6 ─────────────────────────────────────────────────────────────────────
def test_generate_k6_performance_test_markers():
    out = generate_k6_performance_test(K6_SPEC)
    art = out["artifact"]
    assert out["kind"] == "k6_performance"
    assert out["filename"] == "k6-performance-test.js"
    assert "import http from 'k6/http';" in art
    assert "vus: 25," in art
    assert "duration: '1m'," in art
    assert "'http_req_duration'" in art
    assert "'http_req_failed'" in art  # thresholds em ordem alfabética
    assert "http.get('https://api.example.com/health')" in art


def test_generate_k6_requires_target():
    assert generate_k6_performance_test({})["error"] == "missing_target"


# ── 8. Regression suite ───────────────────────────────────────────────────────
def test_generate_regression_suite_markers():
    out = generate_regression_suite(REGRESSION_SPEC)
    art = out["artifact"]
    assert out["kind"] == "regression_suite"
    assert out["filename"] == "regression-suite.yml"
    assert "suite: nightly" in art
    assert "- name: auth" in art
    assert "priority: high" in art
    assert "- login" in art
    assert "- name: billing" in art


def test_generate_regression_requires_modules():
    assert generate_regression_suite({"modules": []})["error"] == "missing_modules"


# ── 9. Smoke suite ────────────────────────────────────────────────────────────
def test_generate_smoke_test_suite_markers():
    out = generate_smoke_test_suite(SMOKE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "smoke_suite"
    assert "suite: smoke" in art
    assert "endpoints:" in art
    assert "method: GET" in art
    assert "path: /health" in art
    assert "pages:" in art
    assert "url: /" in art


def test_generate_smoke_requires_targets():
    assert generate_smoke_test_suite({})["error"] == "missing_targets"


# ── 10. UAT checklist ─────────────────────────────────────────────────────────
def test_generate_uat_checklist_markers():
    out = generate_uat_checklist(UAT_SPEC)
    art = out["artifact"]
    assert out["kind"] == "uat_checklist"
    assert out["filename"] == "uat-checklist.md"
    assert "# UAT Checklist — Checkout" in art
    assert "- [ ] **AC-1** — usuário consegue finalizar a compra" in art
    assert "- [ ] recibo é enviado por e-mail" in art
    assert "## Sign-off" in art


def test_generate_uat_requires_criteria():
    assert generate_uat_checklist({})["error"] == "missing_acceptance_criteria"


# ── 11. Quality gate ──────────────────────────────────────────────────────────
def test_generate_quality_gate_markers():
    out = generate_quality_gate(QUALITY_GATE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "quality_gate_config"
    assert out["filename"] == "quality-gate.json"
    assert '"quality_gate"' in art
    assert '"on_failure": "block"' in art
    assert '"coverage": 80' in art
    assert '"service": "orders-api"' in art


def test_generate_quality_gate_requires_metrics():
    assert generate_quality_gate({"metrics": {}})["error"] == "missing_metrics"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_gherkin_scenarios, GHERKIN_SPEC),
        (generate_unit_tests, UNIT_PYTEST_SPEC),
        (generate_unit_tests, UNIT_JEST_SPEC),
        (generate_e2e_tests, E2E_PLAYWRIGHT_SPEC),
        (generate_e2e_tests, E2E_CYPRESS_SPEC),
        (generate_api_tests, API_SPEC),
        (generate_playwright_tests, PLAYWRIGHT_SPEC),
        (generate_cypress_tests, CYPRESS_SPEC),
        (generate_k6_performance_test, K6_SPEC),
        (generate_regression_suite, REGRESSION_SPEC),
        (generate_smoke_test_suite, SMOKE_SPEC),
        (generate_uat_checklist, UAT_SPEC),
        (generate_quality_gate, QUALITY_GATE_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))


def test_threshold_and_metric_key_ordering_is_stable_regardless_of_input_order():
    # dicts com mesma composição mas ordens de inserção diferentes → mesmo output.
    a = generate_quality_gate({"metrics": {"coverage": 80, "lint": "ok"}})
    b = generate_quality_gate({"metrics": {"lint": "ok", "coverage": 80}})
    assert a == b
    c = generate_k6_performance_test({"target": "http://x", "thresholds": {"a": "x<1", "b": "y<2"}})
    d = generate_k6_performance_test({"target": "http://x", "thresholds": {"b": "y<2", "a": "x<1"}})
    assert c == d
