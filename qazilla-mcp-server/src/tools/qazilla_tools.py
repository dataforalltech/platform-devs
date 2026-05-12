"""QAZilla tools — funções puras que retornam dict."""
from __future__ import annotations

import os


def analyze_quality_requirement(requirement: str, context: dict | None = None) -> dict:
    ctx = context or {}
    return {
        "requirement": requirement,
        "quality_dimensions": ["functional", "performance", "security", "usability", "reliability"],
        "risk_level": "medium",
        "suggested_test_types": ["unit", "integration", "e2e", "api"],
        "automation_feasibility": "high",
        "estimated_test_cases": 15,
        "entry_criteria": ["Código implementado", "Ambiente de teste disponível", "Dados de teste preparados"],
        "exit_criteria": ["100% dos casos críticos passando", "Cobertura >= 80%", "0 bugs P1/P2 abertos"],
        "context": ctx,
    }


def generate_test_plan(feature: str, scope: str = "full", team: str | None = None) -> dict:
    return {
        "title": f"Plano de Teste — {feature}",
        "scope": scope,
        "team": team,
        "objectives": [
            f"Validar comportamento funcional de {feature}",
            "Garantir ausência de regressões",
            "Verificar performance sob carga esperada",
        ],
        "test_levels": {
            "unit": {"coverage_target": "80%", "responsible": "dev"},
            "integration": {"coverage_target": "70%", "responsible": "dev/qa"},
            "e2e": {"coverage_target": "critical paths", "responsible": "qa"},
            "api": {"coverage_target": "all endpoints", "responsible": "qa"},
        },
        "environments": ["dev", "staging"],
        "tools": ["pytest", "playwright", "k6", "postman"],
        "risks": ["Ambiente instável", "Dados de teste inconsistentes"],
        "schedule": {"preparation": "1 dia", "execution": "2 dias", "reporting": "0.5 dia"},
    }


def generate_test_cases(feature: str, test_type: str = "functional", count: int = 5) -> dict:
    cases = []
    for i in range(1, count + 1):
        cases.append({
            "id": f"TC-{i:03d}",
            "title": f"Caso de teste {i} para {feature}",
            "type": test_type,
            "priority": "high" if i == 1 else "medium",
            "preconditions": ["Usuário autenticado", "Ambiente configurado"],
            "steps": [
                {"step": 1, "action": "Acessar funcionalidade", "expected": "Funcionalidade carregada"},
                {"step": 2, "action": "Executar ação principal", "expected": "Resultado esperado exibido"},
                {"step": 3, "action": "Verificar estado final", "expected": "Estado correto persistido"},
            ],
            "expected_result": f"Comportamento esperado de {feature} funcionando corretamente",
            "test_data": {"input": "dados de teste", "expected_output": "saída esperada"},
        })
    return {"feature": feature, "test_type": test_type, "total": count, "cases": cases}


def generate_gherkin_scenarios(feature: str, scenarios: list[str] | None = None) -> dict:
    default_scenarios = scenarios or [
        "fluxo principal com sucesso",
        "validação de dados inválidos",
        "comportamento sem permissão",
    ]
    gherkin_scenarios = []
    for i, scenario in enumerate(default_scenarios, 1):
        gherkin_scenarios.append({
            "id": f"SCN-{i:03d}",
            "name": scenario.title(),
            "gherkin": (
                f"  Scenario: {scenario.title()}\n"
                f"    Given que o usuário está autenticado\n"
                f"    And a funcionalidade '{feature}' está disponível\n"
                f"    When o usuário executa a ação de {scenario}\n"
                f"    Then o sistema deve retornar o resultado esperado\n"
                f"    And o estado deve ser persistido corretamente"
            ),
            "tags": ["@smoke" if i == 1 else "@regression"],
        })
    return {
        "feature": feature,
        "feature_block": f"Feature: {feature}\n  Como usuário do sistema\n  Quero {feature}\n  Para obter valor de negócio",
        "scenarios": gherkin_scenarios,
    }


def generate_e2e_tests(feature: str, framework: str = "playwright", base_url: str | None = None) -> dict:
    base_url = base_url or os.getenv("TEST_APP_URL", "http://localhost:3000")
    if framework == "playwright":
        code = f"""import {{ test, expect }} from '@playwright/test';

test.describe('{feature}', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await page.goto('{base_url}');
    await page.locator('[data-testid="login-email"]').fill('test@example.com');
    await page.locator('[data-testid="login-password"]').fill('password');
    await page.locator('[data-testid="login-submit"]').click();
    await expect(page).toHaveURL('/dashboard');
  }});

  test('deve carregar a funcionalidade corretamente', async ({{ page }}) => {{
    await page.goto('{base_url}/feature');
    await expect(page.locator('h1')).toBeVisible();
  }});

  test('deve executar o fluxo principal com sucesso', async ({{ page }}) => {{
    await page.goto('{base_url}/feature');
    await page.locator('[data-testid="action-button"]').click();
    await expect(page.locator('[data-testid="success-message"]')).toBeVisible();
  }});

  test('deve validar campos obrigatórios', async ({{ page }}) => {{
    await page.goto('{base_url}/feature');
    await page.locator('[data-testid="submit-button"]').click();
    await expect(page.locator('[data-testid="error-message"]')).toBeVisible();
  }});
}});"""
    else:
        code = f"""describe('{feature}', () => {{
  beforeEach(() => {{
    cy.login('test@example.com', 'password');
  }});

  it('deve carregar corretamente', () => {{
    cy.visit('/feature');
    cy.get('h1').should('be.visible');
  }});

  it('deve executar o fluxo principal', () => {{
    cy.visit('/feature');
    cy.get('[data-testid="action-button"]').click();
    cy.get('[data-testid="success-message"]').should('be.visible');
  }});
}});"""

    return {"feature": feature, "framework": framework, "base_url": base_url, "code": code}


def generate_api_tests(endpoint: str, method: str = "GET", base_url: str = "http://localhost:8000") -> dict:
    return {
        "endpoint": endpoint,
        "method": method,
        "base_url": base_url,
        "pytest_code": f"""import pytest
import httpx

BASE_URL = "{base_url}"

class Test{method.title()}{endpoint.replace('/','').title()}:
    def test_success_response(self):
        response = httpx.{method.lower()}(f"{{BASE_URL}}{endpoint}")
        assert response.status_code == 200
        data = response.json()
        assert data is not None

    def test_response_schema(self):
        response = httpx.{method.lower()}(f"{{BASE_URL}}{endpoint}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (dict, list))

    def test_unauthorized_without_token(self):
        response = httpx.{method.lower()}(f"{{BASE_URL}}{endpoint}")
        assert response.status_code in [200, 401, 403]

    def test_invalid_input(self):
        response = httpx.{method.lower()}(f"{{BASE_URL}}{endpoint}", params={{"invalid": "data"}})
        assert response.status_code in [200, 400, 422]
""",
    }


def generate_unit_tests(module: str, language: str = "python") -> dict:
    if language == "python":
        code = f"""import pytest
from unittest.mock import Mock, patch
from {module} import YourClass  # ajuste o import

class TestYourClass:
    @pytest.fixture
    def instance(self):
        return YourClass()

    def test_initialization(self, instance):
        assert instance is not None

    def test_main_method_success(self, instance):
        result = instance.main_method(valid_input="test")
        assert result is not None

    def test_main_method_invalid_input(self, instance):
        with pytest.raises(ValueError):
            instance.main_method(valid_input=None)

    @patch('{module}.external_dependency')
    def test_with_mock(self, mock_dep, instance):
        mock_dep.return_value = {{"status": "ok"}}
        result = instance.method_that_calls_external()
        assert result["status"] == "ok"
        mock_dep.assert_called_once()
"""
    else:
        code = f"""import {{ describe, it, expect, vi }} from 'vitest';
import {{ YourClass }} from './{module}';

describe('{module}', () => {{
  it('should initialize correctly', () => {{
    const instance = new YourClass();
    expect(instance).toBeDefined();
  }});

  it('should execute main method', () => {{
    const instance = new YourClass();
    const result = instance.mainMethod('test');
    expect(result).toBeDefined();
  }});
}});"""
    return {"module": module, "language": language, "code": code}


def generate_playwright_tests(feature: str, base_url: str | None = None) -> dict:
    return generate_e2e_tests(feature, "playwright", base_url)


def generate_cypress_tests(feature: str, base_url: str | None = None) -> dict:
    return generate_e2e_tests(feature, "cypress", base_url)


def generate_postman_collection(api_name: str, base_url: str = "http://localhost:8000", endpoints: list[str] | None = None) -> dict:
    endpoints = endpoints or ["/health", "/api/v1/resource"]
    items = []
    for ep in endpoints:
        items.append({
            "name": f"GET {ep}",
            "request": {
                "method": "GET",
                "url": {"raw": f"{base_url}{ep}", "host": [base_url], "path": ep.split("/")},
                "header": [{"key": "Authorization", "value": "Bearer {{token}}"}],
            },
            "event": [{"listen": "test", "script": {"exec": [
                "pm.test('Status 200', () => pm.response.to.have.status(200));",
                "pm.test('Valid JSON', () => pm.response.to.be.json);",
            ]}}],
        })
    return {
        "info": {"name": api_name, "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": items,
        "variable": [{"key": "token", "value": ""}],
    }


def classify_bug_severity(description: str, impact: str = "medium", frequency: str = "sometimes") -> dict:
    impact_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    freq_map = {"always": 4, "often": 3, "sometimes": 2, "rarely": 1}
    score = impact_map.get(impact, 2) * freq_map.get(frequency, 2)
    severity = "P1" if score >= 9 else "P2" if score >= 6 else "P3" if score >= 3 else "P4"
    return {
        "description": description,
        "severity": severity,
        "impact": impact,
        "frequency": frequency,
        "score": score,
        "sla": {"P1": "4h", "P2": "24h", "P3": "72h", "P4": "backlog"}[severity],
        "recommended_action": {
            "P1": "Hotfix imediato, bloquear deploy",
            "P2": "Corrigir na próxima sprint",
            "P3": "Planejar correção",
            "P4": "Registrar no backlog",
        }[severity],
    }


def generate_bug_report(title: str, steps: list[str] | None = None, severity: str = "P2") -> dict:
    return {
        "title": title,
        "severity": severity,
        "status": "open",
        "environment": "staging",
        "steps_to_reproduce": steps or ["1. Acessar funcionalidade", "2. Executar ação", "3. Observar comportamento"],
        "expected_behavior": "Comportamento esperado conforme especificação",
        "actual_behavior": "Comportamento incorreto observado",
        "logs": "Stack trace ou logs relevantes aqui",
        "attachments": ["screenshot.png"],
        "labels": ["bug", severity.lower()],
    }


def validate_story_testability(story: str, acceptance_criteria: list[str] | None = None) -> dict:
    criteria = acceptance_criteria or []
    issues = []
    if not criteria:
        issues.append("Critérios de aceite não definidos")
    if len(story) < 20:
        issues.append("User story muito vaga — falta contexto")
    score = max(0, 100 - len(issues) * 25)
    return {
        "story": story,
        "testability_score": score,
        "is_testable": score >= 75,
        "issues": issues,
        "suggestions": [
            "Adicionar critérios de aceite mensuráveis",
            "Definir cenários de borda",
            "Especificar dados de teste necessários",
        ] if issues else [],
        "acceptance_criteria_count": len(criteria),
    }


def generate_quality_gate(service: str, thresholds: dict | None = None) -> dict:
    defaults = thresholds or {
        "unit_test_coverage": 80,
        "integration_test_pass_rate": 100,
        "e2e_critical_pass_rate": 100,
        "performance_p95_ms": 500,
        "security_vulnerabilities_critical": 0,
        "security_vulnerabilities_high": 0,
        "code_duplication_percent": 5,
    }
    return {
        "service": service,
        "gates": [
            {"name": k, "threshold": v, "operator": ">=" if "rate" in k or "coverage" in k else "<="}
            for k, v in defaults.items()
        ],
        "blocking": True,
        "ci_config": f"""# Quality Gate — {service}
quality_gate:
  unit_coverage: {defaults['unit_test_coverage']}%
  e2e_critical: {defaults['e2e_critical_pass_rate']}%
  performance_p95: {defaults['performance_p95_ms']}ms
  security_critical: {defaults['security_vulnerabilities_critical']}
""",
    }


def generate_uat_checklist(feature: str, stakeholders: list[str] | None = None) -> dict:
    return {
        "feature": feature,
        "stakeholders": stakeholders or ["Product Owner", "End User", "QA"],
        "checklist": [
            {"item": "Fluxo principal funciona conforme especificado", "category": "functional"},
            {"item": "Fluxos alternativos tratados corretamente", "category": "functional"},
            {"item": "Mensagens de erro são claras e úteis", "category": "usability"},
            {"item": "Performance aceitável (<2s para ações principais)", "category": "performance"},
            {"item": "Acessibilidade: navegação por teclado funciona", "category": "accessibility"},
            {"item": "Funciona nos browsers suportados", "category": "compatibility"},
            {"item": "Dados persistidos corretamente", "category": "data"},
            {"item": "Permissões funcionam como esperado", "category": "security"},
        ],
        "sign_off_required": stakeholders or ["Product Owner"],
    }


def review_test_coverage(module: str, current_coverage: float = 0.0) -> dict:
    gap = max(0, 80.0 - current_coverage)
    return {
        "module": module,
        "current_coverage": current_coverage,
        "target_coverage": 80.0,
        "gap": gap,
        "status": "✅ OK" if gap == 0 else f"⚠️ Faltam {gap:.1f}%",
        "untested_areas": ["error handlers", "edge cases", "authentication paths"] if gap > 0 else [],
        "recommendations": [
            f"Adicionar testes para cobrir os {gap:.0f}% restantes",
            "Priorizar fluxos críticos e de erro",
            "Usar mutation testing para avaliar qualidade dos testes",
        ] if gap > 0 else ["Cobertura atingida — manter qualidade"],
    }


def generate_k6_performance_test(endpoint: str, vus: int = 10, duration: str = "30s") -> dict:
    code = f"""import http from 'k6/http';
import {{ check, sleep }} from 'k6';

export const options = {{
  vus: {vus},
  duration: '{duration}',
  thresholds: {{
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  }},
}};

export default function () {{
  const res = http.get('{endpoint}');
  check(res, {{
    'status 200': (r) => r.status === 200,
    'response < 500ms': (r) => r.timings.duration < 500,
  }});
  sleep(1);
}}
"""
    return {
        "endpoint": endpoint,
        "vus": vus,
        "duration": duration,
        "script": code,
        "thresholds": {"p95_ms": 500, "error_rate": 0.01},
    }


def generate_regression_suite(service: str, test_cases: list[str] | None = None) -> dict:
    cases = test_cases or ["login", "cadastro", "listagem", "criação", "edição", "exclusão"]
    return {
        "service": service,
        "suite_name": f"Regression Suite — {service}",
        "total_cases": len(cases),
        "cases": [{"id": f"REG-{i:03d}", "name": case, "priority": "critical" if i < 3 else "high"}
                  for i, case in enumerate(cases, 1)],
        "execution_order": "parallel",
        "estimated_time": f"{len(cases) * 2} minutos",
        "run_on": ["push to main", "PR merge", "pre-release"],
    }


def generate_smoke_test_suite(service: str, endpoints: list[str] | None = None) -> dict:
    eps = endpoints or ["/health", "/api/v1/status"]
    return {
        "service": service,
        "suite_name": f"Smoke Test Suite — {service}",
        "purpose": "Verificação rápida pós-deploy que o sistema está operacional",
        "max_duration": "5 minutos",
        "tests": [
            {"name": f"Health check {ep}", "endpoint": ep, "expected_status": 200}
            for ep in eps
        ],
        "run_on": ["após cada deploy", "antes de smoke em staging"],
    }
