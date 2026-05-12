"""QAZilla MCP Server — Quality Assurance specialist."""
from __future__ import annotations

import asyncio

from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.qazilla_tools import (
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
from shared.hybrid_server import HybridMCPServer

_TOOLS: dict[str, dict] = {
    "analyze_quality_requirement": {
        "description": "Analisa requisito de qualidade e define estratégia de teste",
        "schema": {
            "type": "object",
            "properties": {
                "requirement": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["requirement"],
        },
    },
    "generate_test_plan": {
        "description": "Gera plano de teste completo",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "scope": {"type": "string", "enum": ["full", "smoke", "regression"]},
                "team": {"type": "string"},
            },
            "required": ["feature"],
        },
    },
    "generate_test_cases": {
        "description": "Gera casos de teste estruturados",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "test_type": {"type": "string", "enum": ["functional", "negative", "boundary", "performance"]},
                "count": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["feature"],
        },
    },
    "generate_gherkin_scenarios": {
        "description": "Gera cenários BDD em formato Gherkin",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "scenarios": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["feature"],
        },
    },
    "generate_e2e_tests": {
        "description": "Gera testes E2E com Playwright ou Cypress",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "framework": {"type": "string", "enum": ["playwright", "cypress"]},
                "base_url": {"type": "string"},
            },
            "required": ["feature"],
        },
    },
    "generate_api_tests": {
        "description": "Gera testes de API",
        "schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                "base_url": {"type": "string"},
            },
            "required": ["endpoint"],
        },
    },
    "generate_unit_tests": {
        "description": "Gera testes unitários",
        "schema": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "language": {"type": "string", "enum": ["python", "typescript"]},
            },
            "required": ["module"],
        },
    },
    "generate_playwright_tests": {
        "description": "Gera testes E2E com Playwright",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "base_url": {"type": "string"},
            },
            "required": ["feature"],
        },
    },
    "generate_cypress_tests": {
        "description": "Gera testes E2E com Cypress",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "base_url": {"type": "string"},
            },
            "required": ["feature"],
        },
    },
    "generate_postman_collection": {
        "description": "Gera coleção Postman para testes de API",
        "schema": {
            "type": "object",
            "properties": {
                "api_name": {"type": "string"},
                "base_url": {"type": "string"},
                "endpoints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["api_name"],
        },
    },
    "classify_bug_severity": {
        "description": "Classifica severidade de bug",
        "schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "impact": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "frequency": {"type": "string", "enum": ["always", "often", "sometimes", "rarely"]},
            },
            "required": ["description"],
        },
    },
    "generate_bug_report": {
        "description": "Gera relatório de bug estruturado",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "severity": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
            },
            "required": ["title"],
        },
    },
    "validate_story_testability": {
        "description": "Valida se user story é testável",
        "schema": {
            "type": "object",
            "properties": {
                "story": {"type": "string"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["story"],
        },
    },
    "generate_quality_gate": {
        "description": "Define quality gate com thresholds",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "thresholds": {"type": "object"},
            },
            "required": ["service"],
        },
    },
    "generate_uat_checklist": {
        "description": "Gera checklist de User Acceptance Testing",
        "schema": {
            "type": "object",
            "properties": {
                "feature": {"type": "string"},
                "stakeholders": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["feature"],
        },
    },
    "review_test_coverage": {
        "description": "Avalia cobertura de testes",
        "schema": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "current_coverage": {"type": "number", "minimum": 0, "maximum": 100},
            },
            "required": ["module"],
        },
    },
    "generate_k6_performance_test": {
        "description": "Gera script k6 de teste de performance",
        "schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string"},
                "vus": {"type": "integer", "minimum": 1},
                "duration": {"type": "string"},
            },
            "required": ["endpoint"],
        },
    },
    "generate_regression_suite": {
        "description": "Gera suíte de testes de regressão",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "test_cases": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["service"],
        },
    },
    "generate_smoke_test_suite": {
        "description": "Gera suíte de smoke tests",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "endpoints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["service"],
        },
    },
}

_DISPATCH = {
    "analyze_quality_requirement": lambda a: analyze_quality_requirement(a["requirement"], a.get("context")),
    "generate_test_plan": lambda a: generate_test_plan(a["feature"], a.get("scope", "full"), a.get("team")),
    "generate_test_cases": lambda a: generate_test_cases(a["feature"], a.get("test_type", "functional"), a.get("count", 5)),
    "generate_gherkin_scenarios": lambda a: generate_gherkin_scenarios(a["feature"], a.get("scenarios")),
    "generate_e2e_tests": lambda a: generate_e2e_tests(a["feature"], a.get("framework", "playwright"), a.get("base_url", "http://localhost:3000")),
    "generate_api_tests": lambda a: generate_api_tests(a["endpoint"], a.get("method", "GET"), a.get("base_url", "http://localhost:8000")),
    "generate_unit_tests": lambda a: generate_unit_tests(a["module"], a.get("language", "python")),
    "generate_playwright_tests": lambda a: generate_playwright_tests(a["feature"], a.get("base_url", "http://localhost:3000")),
    "generate_cypress_tests": lambda a: generate_cypress_tests(a["feature"], a.get("base_url", "http://localhost:3000")),
    "generate_postman_collection": lambda a: generate_postman_collection(a["api_name"], a.get("base_url", "http://localhost:8000"), a.get("endpoints")),
    "classify_bug_severity": lambda a: classify_bug_severity(a["description"], a.get("impact", "medium"), a.get("frequency", "sometimes")),
    "generate_bug_report": lambda a: generate_bug_report(a["title"], a.get("steps"), a.get("severity", "P2")),
    "validate_story_testability": lambda a: validate_story_testability(a["story"], a.get("acceptance_criteria")),
    "generate_quality_gate": lambda a: generate_quality_gate(a["service"], a.get("thresholds")),
    "generate_uat_checklist": lambda a: generate_uat_checklist(a["feature"], a.get("stakeholders")),
    "review_test_coverage": lambda a: review_test_coverage(a["module"], a.get("current_coverage", 0.0)),
    "generate_k6_performance_test": lambda a: generate_k6_performance_test(a["endpoint"], a.get("vus", 10), a.get("duration", "30s")),
    "generate_regression_suite": lambda a: generate_regression_suite(a["service"], a.get("test_cases")),
    "generate_smoke_test_suite": lambda a: generate_smoke_test_suite(a["service"], a.get("endpoints")),
}


def main() -> None:
    server = HybridMCPServer("qazilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=7100))


if __name__ == "__main__":
    main()
