"""Catálogo de tools + dispatcher do domínio *qa* (consolidado no devteam-mcp).

Fatia "de negócio" do antigo ``qa-mcp-server/src/server/mcp_server.py``: mantém intactos o
``_TOOL_SCHEMAS`` (metadados de policy por tool) e o dispatcher (roteamento op → handler).
O que ficou de FORA é o boot/serve/segurança (FastAPI, PEP inner-token, stdio, tenant
plumbing) — responsabilidade do AGREGADOR (``src/server/mcp_server.py``), compartilhado.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.qa_<op>`` (namespace do server consolidado + nome
    de tool já prefixado pelo domínio — o gateway não deriva por nome).
  * ``required_scope`` passa a ``qa:<recurso>:<ação>`` — PRESERVA o least-privilege
    por-tool (data_domain intacto); só troca o antigo prefixo de namespace ``qa-mcp`` pelo
    domínio canônico ``qa``.
  * As CHAVES de ``_TOOL_SCHEMAS`` continuam os nomes de op SEM prefixo (``run_unit_tests``);
    o ``plugin.register()`` prefixa (``qa_run_unit_tests``) e o ``plugin.dispatch`` retira o
    prefixo antes de chamar ``dispatch`` — a lógica de roteamento fica byte-a-byte idêntica.

As tools do qa recebem, além do ``store``, um objeto ``settings`` com os knobs de compute
QA-específicos (screenshots/thresholds/timeouts). As settings de DB/gateway/segurança são
do AGREGADOR (não duplicadas aqui); este módulo só carrega os knobs ``QA_*`` que as tools
leem — ``_QASettings`` (defaults 1:1 do fonte, prefixo de env ``QA_``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from .db.store import QAStore
from .tools.analysis_tool import (
    analyze_complexity,
    check_dependencies,
    run_linter,
    run_security_scan,
    run_type_check,
)
from .tools.api_tool import generate_test_matrix, run_api_tests
from .tools.browser_tool import check_accessibility, screenshot_page, visual_regression
from .tools.report_tool import generate_qa_report, get_coverage_report
from .tools.test_tool import run_e2e_tests, run_unit_tests

# Domínio canônico deste plugin — prefixo de tool + capability/required_scope
# (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "qa"
# Namespace original do server-fonte, preservado no payload de ``status`` (campo service).
NAMESPACE = "qa-mcp"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Bloco byte-a-byte do fonte; só ``capability`` (→ ``devteam-mcp.qa_<op>``) e
# ``required_scope`` (→ ``qa:<res>:<ação>``, dropando o antigo prefixo ``qa-mcp``) mudam.
# inputSchema MUST ser type=object com properties. Execuções/geração usam :write;
# análise/relatório :read.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "status": {
        "description": "Retorna o status real do servidor (nome, versão, nº de tools).",
        "capability": "devteam-mcp.qa_status",
        "required_scope": "qa:status:read",
        "resource_type": "status",
        "data_domain": "operational",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "run_unit_tests": {
        "description": (
            "Roda testes unitários (pytest/jest) com cobertura opcional. Detecta framework automaticamente."
        ),
        "capability": "devteam-mcp.qa_run_unit_tests",
        "required_scope": "qa:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_run_e2e_tests",
        "required_scope": "qa:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_run_api_tests",
        "required_scope": "qa:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_generate_test_matrix",
        "required_scope": "qa:test:write",
        "resource_type": "test_run",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_screenshot_page",
        "required_scope": "qa:screenshot:write",
        "resource_type": "screenshot",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_check_accessibility",
        "required_scope": "qa:accessibility:read",
        "resource_type": "accessibility_report",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_visual_regression",
        "required_scope": "qa:visual:write",
        "resource_type": "visual_diff",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_run_linter",
        "required_scope": "qa:analysis:read",
        "resource_type": "analysis",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_run_security_scan",
        "required_scope": "qa:security:read",
        "resource_type": "security_scan",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_check_dependencies",
        "required_scope": "qa:dependency:read",
        "resource_type": "dependency_scan",
        "data_domain": "quality",
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
            "Type checking com mypy (Python) ou tsc (TypeScript). Retorna erros e warnings por arquivo."
        ),
        "capability": "devteam-mcp.qa_run_type_check",
        "required_scope": "qa:analysis:read",
        "resource_type": "analysis",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_analyze_complexity",
        "required_scope": "qa:analysis:read",
        "resource_type": "analysis",
        "data_domain": "quality",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo_path": {"type": "string"},
                "threshold": {
                    "type": "integer",
                    "description": "CC máximo antes de considerar complexo (default: complexity_threshold)",
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
        "capability": "devteam-mcp.qa_get_coverage_report",
        "required_scope": "qa:coverage:read",
        "resource_type": "coverage_report",
        "data_domain": "quality",
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
        "capability": "devteam-mcp.qa_generate_qa_report",
        "required_scope": "qa:report:read",
        "resource_type": "qa_report",
        "data_domain": "quality",
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


# ── Settings de compute QA-específicas (knobs ``QA_*`` do fonte) ───────────────
# O agregador é dono das settings de DB/gateway/segurança; aqui vivem só os knobs que as
# tools do qa leem (o server-fonte os expunha na sua QASettings — preservados 1:1).
class _QASettings(BaseSettings):
    """Knobs de compute lidos pelas tools do qa (screenshots/thresholds/timeouts).

    Preservados 1:1 do ``qa-mcp-server`` (prefixo de env ``QA_``). NÃO duplica as settings
    de DB/gateway/segurança — essas são do agregador; o domínio só precisa dos knobs que as
    tools acessam.
    """

    model_config = SettingsConfigDict(
        env_prefix="QA_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    screenshots_dir: str = str(Path.home() / ".qa-mcp" / "screenshots")
    baselines_dir: str = str(Path.home() / ".qa-mcp" / "baselines")

    http_timeout: float = 10.0
    browser_timeout: int = 30_000  # ms para Playwright
    subprocess_timeout: int = 120  # segundos para processos externos

    default_browser: str = "chromium"  # chromium | firefox | webkit
    headless: bool = True

    complexity_threshold: int = 10  # CC > 10 é "complexo"
    coverage_threshold: float = 80.0  # % mínimo de cobertura


@lru_cache(maxsize=1)
def get_settings() -> _QASettings:
    return _QASettings()


def _status() -> dict[str, Any]:
    """Status real do servidor (compute-only, sem store)."""
    return {
        "status": "ok",
        "service": NAMESPACE,
        "version": "0.1.0",
        "tools": len(_TOOL_SCHEMAS),
    }


# ── Dispatcher (async; store tenant-scoped ligado ao pool + settings de compute) ──


async def dispatch(name: str, args: dict[str, Any], settings: Any, store: QAStore) -> dict:
    """Despacha a chamada para a função de tool (async). ``name`` é o nome de op SEM prefixo
    de domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3): o
    ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    if name == "status":
        return _status()
    # ---- test_tool ----
    if name == "run_unit_tests":
        return await run_unit_tests(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
            test_path=args.get("test_path", "."),
            coverage=args.get("coverage", False),
            timeout=args.get("timeout"),
        )
    if name == "run_e2e_tests":
        return await run_e2e_tests(
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
        return await run_api_tests(
            store,
            settings,
            base_url=args.get("base_url", ""),
            endpoints=args.get("endpoints") or [],
            timeout=args.get("timeout"),
        )
    if name == "generate_test_matrix":
        return await generate_test_matrix(
            store,
            settings,
            base_url=args.get("base_url", ""),
            scenarios=args.get("scenarios") or [],
        )
    # ---- browser_tool ----
    if name == "screenshot_page":
        return await screenshot_page(
            store,
            settings,
            url=args.get("url", ""),
            viewport=args.get("viewport", "desktop"),
            selector=args.get("selector"),
            output_dir=args.get("output_dir"),
        )
    if name == "check_accessibility":
        return await check_accessibility(
            store,
            settings,
            url=args.get("url", ""),
            standard=args.get("standard", "WCAG2AA"),
        )
    if name == "visual_regression":
        return await visual_regression(
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
        return await run_linter(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
            fix=args.get("fix", False),
        )
    if name == "run_security_scan":
        return await run_security_scan(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "check_dependencies":
        return await check_dependencies(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
        )
    if name == "run_type_check":
        return await run_type_check(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "analyze_complexity":
        return await analyze_complexity(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            threshold=args.get("threshold"),
        )
    # ---- report_tool ----
    if name == "get_coverage_report":
        return await get_coverage_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            framework=args.get("framework", "auto"),
        )
    if name == "generate_qa_report":
        return await generate_qa_report(
            store,
            settings,
            repo_path=args.get("repo_path", ""),
            last_n_runs=args.get("last_n_runs", 1),
        )
    raise KeyError(name)
