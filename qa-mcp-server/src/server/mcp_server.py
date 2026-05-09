"""Servidor MCP QA — 14 tools para testes, análise e qualidade."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from ..config.settings import QASettings, get_settings
from ..db.store import QAStore
from ..tools.analysis_tool import (
    analyze_complexity,
    check_dependencies,
    run_linter,
    run_security_scan,
    run_type_check,
)
from ..tools.api_tool import generate_test_matrix, run_api_tests
from ..tools.browser_tool import check_accessibility, screenshot_page, visual_regression
from ..tools.report_tool import generate_qa_report, get_coverage_report
from ..tools.test_tool import run_e2e_tests, run_unit_tests

# ---------------------------------------------------------------------- #
# Schemas                                                                 #
# ---------------------------------------------------------------------- #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "run_unit_tests": {
        "description": (
            "Roda testes unitários (pytest/jest) com cobertura opcional. "
            "Detecta framework automaticamente."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Caminho absoluto do repositório",
                },
                "framework": {
                    "type": "string",
                    "enum": ["auto", "pytest", "jest"],
                    "default": "auto",
                },
                "test_path": {"type": "string", "default": "."},
                "coverage": {"type": "boolean", "default": False},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout em segundos",
                },
            },
            "required": ["repo_path"],
        },
    },
    "run_e2e_tests": {
        "description": (
            "Roda testes E2E via Playwright (test_*.py ou *.spec.ts). "
            "Detecta tipo de arquivo e usa comando correto."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Diretório com os testes E2E",
                },
                "base_url": {
                    "type": "string",
                    "description": "URL base da aplicação",
                },
                "browser": {
                    "type": "string",
                    "enum": ["chromium", "firefox", "webkit"],
                    "default": "chromium",
                },
                "headless": {"type": "boolean", "default": True},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout em segundos",
                },
            },
            "required": ["test_path", "base_url"],
        },
    },
    "run_api_tests": {
        "description": (
            "Testa endpoints HTTP com verificação de status e chaves de resposta. "
            "Suporta GET, POST, PUT, DELETE com headers e body customizados."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "base_url": {
                    "type": "string",
                    "description": "URL base da API (ex: http://localhost:8000)",
                },
                "endpoints": {
                    "type": "array",
                    "description": "Lista de endpoints a testar",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "method": {"type": "string"},
                            "headers": {"type": "object"},
                            "body": {"type": "object"},
                            "expect_status": {"type": "integer"},
                            "expect_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["path"],
                    },
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout HTTP em segundos",
                },
            },
            "required": ["base_url", "endpoints"],
        },
    },
    "generate_test_matrix": {
        "description": (
            "Gera e executa matriz de testes: cada cenário × payload é um caso. "
            "Ideal para testar variações de input em endpoints."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "base_url": {"type": "string"},
                "scenarios": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "endpoint": {"type": "string"},
                            "method": {"type": "string"},
                            "payloads": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                            "expected_statuses": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "expected_keys": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                        "required": ["name", "endpoint"],
                    },
                },
            },
            "required": ["base_url", "scenarios"],
        },
    },
    "screenshot_page": {
        "description": (
            "Tira screenshot de uma página via Playwright. "
            "Suporta viewports desktop/tablet/mobile e captura de elemento por selector."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "URL da página"},
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "tablet", "mobile"],
                    "default": "desktop",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector para capturar elemento específico",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Diretório de saída (default: settings.screenshots_dir)",
                },
            },
            "required": ["url"],
        },
    },
    "check_accessibility": {
        "description": (
            "Verifica acessibilidade via Playwright + axe-core. "
            "Suporta WCAG2A, WCAG2AA, WCAG2AAA. Retorna violations, passes e incomplete."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "URL da página a verificar"},
                "standard": {
                    "type": "string",
                    "enum": ["WCAG2A", "WCAG2AA", "WCAG2AAA"],
                    "default": "WCAG2AA",
                },
            },
            "required": ["url"],
        },
    },
    "visual_regression": {
        "description": (
            "Compara screenshot atual com baseline via Pillow. "
            "Cria baseline se não existir. Retorna diff em % de pixels."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string"},
                "baseline_name": {
                    "type": "string",
                    "description": "Nome do baseline (sem extensão)",
                },
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "tablet", "mobile"],
                    "default": "desktop",
                },
                "threshold_pct": {
                    "type": "number",
                    "description": "% máximo de pixels diferentes para passar",
                    "default": 2.0,
                },
                "update_baseline": {
                    "type": "boolean",
                    "description": "Se True, salva novo baseline",
                    "default": False,
                },
            },
            "required": ["url", "baseline_name"],
        },
    },
    "run_linter": {
        "description": (
            "Análise estática com ruff (Python) ou eslint (JS/TS). "
            "Detecta framework automaticamente. Suporta fix automático."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
                "fix": {
                    "type": "boolean",
                    "default": False,
                    "description": "Aplicar correções automáticas",
                },
            },
            "required": ["repo_path"],
        },
    },
    "run_security_scan": {
        "description": (
            "Scan de segurança com bandit (Python) ou npm audit (JS/TS). "
            "Classifica por severity: HIGH, MEDIUM, LOW."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
            },
            "required": ["repo_path"],
        },
    },
    "check_dependencies": {
        "description": (
            "Verifica vulnerabilidades em dependências com pip-audit/safety (Python) "
            "ou npm audit (Node). Detecta tipo de projeto automaticamente."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
            },
            "required": ["repo_path"],
        },
    },
    "run_type_check": {
        "description": (
            "Type checking com mypy (Python) ou tsc (TypeScript). "
            "Retorna erros e warnings por arquivo."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
            },
            "required": ["repo_path"],
        },
    },
    "analyze_complexity": {
        "description": (
            "Analisa complexidade ciclomática com radon (Python) ou grep simples (JS/TS). "
            "Identifica hotspots acima do threshold."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "threshold": {
                    "type": "integer",
                    "description": "CC máximo antes de considerar complexo (default: settings.complexity_threshold)",
                },
            },
            "required": ["repo_path"],
        },
    },
    "get_coverage_report": {
        "description": (
            "Lê relatório de cobertura de testes. "
            "Python: coverage.json; Jest: coverage/coverage-summary.json."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["auto", "python", "javascript", "typescript"],
                    "default": "auto",
                },
            },
            "required": ["repo_path"],
        },
    },
    "generate_qa_report": {
        "description": (
            "Gera relatório QA agregado com score 0-100 e grade A-F. "
            "Pondera: unit_tests 30%, security 25%, linter 20%, coverage 15%, dependencies 10%."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "last_n_runs": {
                    "type": "integer",
                    "description": "Considera último N run de cada tipo",
                    "default": 1,
                },
            },
            "required": ["repo_path"],
        },
    },
}


# ---------------------------------------------------------------------- #
# Server                                                                  #
# ---------------------------------------------------------------------- #
def build_server() -> tuple[Server, QASettings, QAStore]:
    settings = get_settings()

    store = QAStore(db_path=settings.db_path)

    server: Server = Server("qa-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=meta["description"],
                inputSchema=meta["schema"],
            )
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, settings, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(exc), "tool": name}

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, store


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: QASettings,
    store: QAStore,
) -> dict:
    # ---- test_tool ----
    if name == "run_unit_tests":
        return run_unit_tests(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
            test_path=args.get("test_path", "."),
            coverage=args.get("coverage", False),
            timeout=args.get("timeout"),
        )
    if name == "run_e2e_tests":
        return run_e2e_tests(
            store,
            settings,
            test_path=args.get("test_path", ""),
            base_url=args.get("base_url", ""),
            browser=args.get("browser", "chromium"),
            headless=args.get("headless", True),
            timeout=args.get("timeout"),
        )
    # ---- api_tool ----
    if name == "run_api_tests":
        return run_api_tests(
            store,
            settings,
            base_url=args.get("base_url", ""),
            endpoints=args.get("endpoints") or [],
            timeout=args.get("timeout"),
        )
    if name == "generate_test_matrix":
        return generate_test_matrix(
            store,
            settings,
            base_url=args.get("base_url", ""),
            scenarios=args.get("scenarios") or [],
        )
    # ---- browser_tool ----
    if name == "screenshot_page":
        return screenshot_page(
            store,
            settings,
            url=args.get("url", ""),
            viewport=args.get("viewport", "desktop"),
            selector=args.get("selector"),
            output_dir=args.get("output_dir"),
        )
    if name == "check_accessibility":
        return check_accessibility(
            store,
            settings,
            url=args.get("url", ""),
            standard=args.get("standard", "WCAG2AA"),
        )
    if name == "visual_regression":
        return visual_regression(
            store,
            settings,
            url=args.get("url", ""),
            baseline_name=args.get("baseline_name", ""),
            viewport=args.get("viewport", "desktop"),
            threshold_pct=args.get("threshold_pct", 2.0),
            update_baseline=args.get("update_baseline", False),
        )
    # ---- analysis_tool ----
    if name == "run_linter":
        return run_linter(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
            fix=args.get("fix", False),
        )
    if name == "run_security_scan":
        return run_security_scan(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "check_dependencies":
        return check_dependencies(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
        )
    if name == "run_type_check":
        return run_type_check(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "analyze_complexity":
        return analyze_complexity(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            threshold=args.get("threshold"),
        )
    # ---- report_tool ----
    if name == "get_coverage_report":
        return get_coverage_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "generate_qa_report":
        return generate_qa_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            last_n_runs=args.get("last_n_runs", 1),
        )
    raise KeyError(name)


async def _run() -> None:
    server, _settings, _store = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
