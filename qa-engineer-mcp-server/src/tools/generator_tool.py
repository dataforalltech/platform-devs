"""Geradores determinísticos de artefatos de QA (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``), estas tools NÃO tocam o
``QAEngineerStore``: são funções puras ``spec: dict -> dict`` que renderizam
artefatos de teste (Gherkin, unit/e2e/API tests, specs Playwright/Cypress, script
k6, suites de regressão/smoke, checklist UAT e config de quality gate) por template
de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str|dict>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. Chaves de dicionários de entrada (thresholds/metrics) são
renderizadas em ordem alfabética estável, de modo que a MESMA spec produza SEMPRE o
MESMO output byte-a-byte. Listas preservam a ordem da spec (que já é determinística).
Só depende da stdlib → importável/testável sem banco.

O gerador FORMATA/scaffolda a spec fornecida; quando algum conteúdo não vier, usa
defaults/placeholders sensatos — NÃO inventa conteúdo de domínio (isso é do agente).
"""

from __future__ import annotations

import json
import re
from typing import Any

# ── Constantes de suporte ─────────────────────────────────────────────────────
SUPPORTED_UNIT_FRAMEWORKS = frozenset({"pytest", "jest"})
SUPPORTED_E2E_FRAMEWORKS = frozenset({"playwright", "cypress"})


# ── Helpers de renderização (determinísticos) ─────────────────────────────────
def _slug(text: Any) -> str:
    """Normaliza texto p/ identificador estável (minúsculas, ``_`` entre tokens)."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(text).strip().lower()).strip("_")
    return s or "item"


def _js_str(value: Any) -> str:
    """Escapa uma string p/ literal JS entre aspas simples."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _yaml_scalar(value: Any) -> str:
    """Renderiza um escalar YAML. Bool/int/float saem crus; o resto é aspado."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"{}"'.format(str(value).replace('"', '\\"'))


def _playwright_action(action: Any) -> str:
    """Renderiza uma ação Playwright (dict {type,selector,value}) ou comentário."""
    if not isinstance(action, dict):
        return f"// {action}"
    atype = str(action.get("type", "")).strip().lower()
    selector = _js_str(action.get("selector") or action.get("target") or "")
    value = _js_str(action.get("value", ""))
    if atype in ("goto", "visit"):
        return f"await page.goto('{value or selector}');"
    if atype == "click":
        return f"await page.click('{selector}');"
    if atype in ("fill", "type"):
        return f"await page.fill('{selector}', '{value}');"
    if atype in ("expect_text", "assert_text"):
        return f"await expect(page.locator('{selector}')).toHaveText('{value}');"
    return f"// {atype or 'action'} {selector}".rstrip()


def _cypress_action(action: Any) -> str:
    """Renderiza uma ação Cypress (dict {type,selector,value}) ou comentário."""
    if not isinstance(action, dict):
        return f"// {action}"
    atype = str(action.get("type", "")).strip().lower()
    selector = _js_str(action.get("selector") or action.get("target") or "")
    value = _js_str(action.get("value", ""))
    if atype in ("goto", "visit"):
        return f"cy.visit('{value or selector}');"
    if atype == "click":
        return f"cy.get('{selector}').click();"
    if atype in ("fill", "type"):
        return f"cy.get('{selector}').type('{value}');"
    if atype in ("expect_text", "assert_text"):
        return f"cy.contains('{value}');"
    return f"// {atype or 'action'} {selector}".rstrip()


# ── 1. Cenários Gherkin (.feature) ────────────────────────────────────────────
def generate_gherkin_scenarios(spec: dict[str, Any]) -> dict[str, Any]:
    feature = str(spec.get("feature", "")).strip()
    if not feature:
        return {"error": "missing_feature"}
    scenarios = spec.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return {"error": "missing_scenarios"}

    lines: list[str] = [f"Feature: {feature}"]
    description = spec.get("description")
    if description:
        lines.append(f"  {description}")
    lines.append("")

    for idx, scenario in enumerate(scenarios):
        name = str(scenario.get("name") or f"Scenario {idx + 1}").strip()
        lines.append(f"  Scenario: {name}")
        for keyword, key in (("Given", "given"), ("When", "when"), ("Then", "then")):
            steps = scenario.get(key)
            if steps is None:
                steps = [f"<{key}>"]
            elif isinstance(steps, str):
                steps = [steps]
            for step_idx, step in enumerate(steps):
                kw = keyword if step_idx == 0 else "And"
                lines.append(f"    {kw} {step}")
        lines.append("")

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": f"{_slug(feature)}.feature",
        "kind": "gherkin",
    }


# ── 2. Testes unitários (pytest|jest) ─────────────────────────────────────────
def generate_unit_tests(spec: dict[str, Any]) -> dict[str, Any]:
    framework = str(spec.get("framework", "")).strip().lower()
    if framework not in SUPPORTED_UNIT_FRAMEWORKS:
        return {
            "error": "unsupported_framework",
            "framework": framework,
            "valid": sorted(SUPPORTED_UNIT_FRAMEWORKS),
        }
    target = str(spec.get("target", "")).strip()
    if not target:
        return {"error": "missing_target"}

    cases = spec.get("cases") or [{"name": "placeholder"}]

    if framework == "pytest":
        lines: list[str] = [f'"""Unit tests for {target} (scaffold — preencha os asserts)."""', ""]
        for idx, case in enumerate(cases):
            name = case.get("name") if isinstance(case, dict) else case
            fn = _slug(name or f"case_{idx + 1}")
            desc = case.get("description") if isinstance(case, dict) else None
            lines.append(f"def test_{fn}():")
            if desc:
                lines.append(f"    # {desc}")
            lines.append("    # TODO: arrange / act")
            lines.append("    assert True  # TODO: substituir pela asserção real")
            lines.append("")
        artifact = "\n".join(lines).rstrip() + "\n"
        filename = f"test_{_slug(target)}.py"
    else:  # jest
        lines = [f"describe('{_js_str(target)}', () => {{"]
        for idx, case in enumerate(cases):
            name = case.get("name") if isinstance(case, dict) else case
            title = _js_str(name or f"case {idx + 1}")
            lines.append(f"  test('{title}', () => {{")
            lines.append("    // TODO: arrange / act")
            lines.append("    expect(true).toBe(true); // TODO: asserção real")
            lines.append("  });")
        lines.append("});")
        artifact = "\n".join(lines) + "\n"
        filename = f"{_slug(target)}.test.js"

    return {"artifact": artifact, "filename": filename, "kind": "unit_tests"}


# ── 3. Testes e2e (playwright|cypress) ────────────────────────────────────────
def generate_e2e_tests(spec: dict[str, Any]) -> dict[str, Any]:
    framework = str(spec.get("framework", "")).strip().lower()
    if framework not in SUPPORTED_E2E_FRAMEWORKS:
        return {
            "error": "unsupported_framework",
            "framework": framework,
            "valid": sorted(SUPPORTED_E2E_FRAMEWORKS),
        }
    flows = spec.get("flows")
    if not isinstance(flows, list) or not flows:
        return {"error": "missing_flows"}

    suite = str(spec.get("suite") or "e2e")

    if framework == "playwright":
        lines: list[str] = [
            "import { test, expect } from '@playwright/test';",
            "",
            f"test.describe('{_js_str(suite)}', () => {{",
        ]
        for idx, flow in enumerate(flows):
            name = flow.get("name") if isinstance(flow, dict) else flow
            steps = flow.get("steps") if isinstance(flow, dict) else None
            lines.append(f"  test('{_js_str(name or f'flow {idx + 1}')}', async ({{ page }}) => {{")
            for step in steps or []:
                lines.append(
                    f"    // {step}" if not isinstance(step, dict) else f"    {_playwright_action(step)}"
                )
            if not steps:
                lines.append("    // TODO: adicionar passos do fluxo")
            lines.append("  });")
        lines.append("});")
        artifact = "\n".join(lines) + "\n"
        filename = f"{_slug(suite)}.e2e.spec.ts"
    else:  # cypress
        lines = [f"describe('{_js_str(suite)}', () => {{"]
        for idx, flow in enumerate(flows):
            name = flow.get("name") if isinstance(flow, dict) else flow
            steps = flow.get("steps") if isinstance(flow, dict) else None
            lines.append(f"  it('{_js_str(name or f'flow {idx + 1}')}', () => {{")
            for step in steps or []:
                lines.append(
                    f"    // {step}" if not isinstance(step, dict) else f"    {_cypress_action(step)}"
                )
            if not steps:
                lines.append("    // TODO: adicionar passos do fluxo")
            lines.append("  });")
        lines.append("});")
        artifact = "\n".join(lines) + "\n"
        filename = f"{_slug(suite)}.e2e.cy.js"

    return {"artifact": artifact, "filename": filename, "kind": "e2e_tests"}


# ── 4. Testes de API (pytest + requests) ──────────────────────────────────────
def generate_api_tests(spec: dict[str, Any]) -> dict[str, Any]:
    base = str(spec.get("base", "")).strip()
    if not base:
        return {"error": "missing_base"}
    endpoints = spec.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        return {"error": "missing_endpoints"}

    lines: list[str] = [
        f'"""API tests for {base} (scaffold — preencha payloads/asserts)."""',
        "",
        "import requests",
        "",
        f'BASE_URL = "{base}"',
        "",
    ]
    for endpoint in endpoints:
        method = str(endpoint.get("method") or "get").strip().lower()
        path = str(endpoint.get("path") or "/")
        status = int(endpoint.get("expected_status", endpoint.get("status", 200)))
        name = endpoint.get("name") or f"{method}_{_slug(path)}"
        lines.append(f"def test_{_slug(name)}():")
        lines.append(f'    resp = requests.{method}(f"{{BASE_URL}}{path}")')
        lines.append(f"    assert resp.status_code == {status}")
        lines.append("")

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": "test_api.py",
        "kind": "api_tests",
    }


# ── 5. Spec Playwright (pages + actions) ──────────────────────────────────────
def generate_playwright_tests(spec: dict[str, Any]) -> dict[str, Any]:
    pages = spec.get("pages") or [{"name": "home", "url": "/"}]
    actions = spec.get("actions") or []
    suite = str(spec.get("suite") or "playwright suite")

    lines: list[str] = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"test.describe('{_js_str(suite)}', () => {{",
    ]
    for idx, page in enumerate(pages):
        if isinstance(page, dict):
            name = page.get("name") or page.get("url") or f"page {idx + 1}"
            url = page.get("url") or page.get("name") or "/"
        else:
            name = url = page
        lines.append(f"  test('{_js_str(name)}', async ({{ page }}) => {{")
        lines.append(f"    await page.goto('{_js_str(url)}');")
        for action in actions:
            lines.append(f"    {_playwright_action(action)}")
        if not actions:
            lines.append("    // TODO: adicionar ações")
        lines.append("  });")
    lines.append("});")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"{_slug(suite)}.spec.ts",
        "kind": "playwright",
    }


# ── 6. Spec Cypress (pages + actions) ─────────────────────────────────────────
def generate_cypress_tests(spec: dict[str, Any]) -> dict[str, Any]:
    pages = spec.get("pages") or [{"name": "home", "url": "/"}]
    actions = spec.get("actions") or []
    suite = str(spec.get("suite") or "cypress suite")

    lines: list[str] = [f"describe('{_js_str(suite)}', () => {{"]
    for idx, page in enumerate(pages):
        if isinstance(page, dict):
            name = page.get("name") or page.get("url") or f"page {idx + 1}"
            url = page.get("url") or page.get("name") or "/"
        else:
            name = url = page
        lines.append(f"  it('{_js_str(name)}', () => {{")
        lines.append(f"    cy.visit('{_js_str(url)}');")
        for action in actions:
            lines.append(f"    {_cypress_action(action)}")
        if not actions:
            lines.append("    // TODO: adicionar ações")
        lines.append("  });")
    lines.append("});")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"{_slug(suite)}.cy.js",
        "kind": "cypress",
    }


# ── 7. Teste de performance k6 ────────────────────────────────────────────────
def generate_k6_performance_test(spec: dict[str, Any]) -> dict[str, Any]:
    target = str(spec.get("target", "")).strip()
    if not target:
        return {"error": "missing_target"}

    vus = int(spec.get("vus", 10))
    duration = str(spec.get("duration") or "30s")
    thresholds = spec.get("thresholds") or {
        "http_req_duration": ["p(95)<500"],
        "http_req_failed": ["rate<0.01"],
    }

    thr_lines: list[str] = []
    for key in sorted(thresholds):
        cond = thresholds[key]
        if isinstance(cond, str):
            cond = [cond]
        rendered = ", ".join(json.dumps(str(c)) for c in cond)
        thr_lines.append(f"    '{key}': [{rendered}],")

    artifact = (
        "import http from 'k6/http';\n"
        "import { check, sleep } from 'k6';\n\n"
        "export const options = {\n"
        f"  vus: {vus},\n"
        f"  duration: '{duration}',\n"
        "  thresholds: {\n" + "\n".join(thr_lines) + "\n  },\n"
        "};\n\n"
        "export default function () {\n"
        f"  const res = http.get('{_js_str(target)}');\n"
        "  check(res, { 'status is 200': (r) => r.status === 200 });\n"
        "  sleep(1);\n"
        "}\n"
    )
    return {"artifact": artifact, "filename": "k6-performance-test.js", "kind": "k6_performance"}


# ── 8. Suite de regressão (manifesto YAML) ────────────────────────────────────
def generate_regression_suite(spec: dict[str, Any]) -> dict[str, Any]:
    modules = spec.get("modules")
    if not isinstance(modules, list) or not modules:
        return {"error": "missing_modules"}

    suite_name = str(spec.get("name") or "regression")
    lines: list[str] = [f"suite: {suite_name}", "kind: regression", "modules:"]
    for idx, module in enumerate(modules):
        if isinstance(module, dict):
            name = module.get("name") or f"module-{idx + 1}"
            priority = module.get("priority")
            cases = module.get("cases") or []
        else:
            name, priority, cases = module, None, []
        lines.append(f"  - name: {name}")
        if priority:
            lines.append(f"    priority: {priority}")
        if cases:
            lines.append("    cases:")
            for case in cases:
                cname = case.get("name") or case.get("title") if isinstance(case, dict) else case
                lines.append(f"      - {cname}")
        else:
            lines.append("    cases: []")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "regression-suite.yml",
        "kind": "regression_suite",
    }


# ── 9. Suite de smoke (manifesto YAML) ────────────────────────────────────────
def generate_smoke_test_suite(spec: dict[str, Any]) -> dict[str, Any]:
    endpoints = spec.get("endpoints") or []
    pages = spec.get("pages") or []
    if not endpoints and not pages:
        return {"error": "missing_targets"}

    lines: list[str] = ["suite: smoke", "kind: smoke", "checks:"]
    if endpoints:
        lines.append("  endpoints:")
        for endpoint in endpoints:
            if isinstance(endpoint, dict):
                method = str(endpoint.get("method") or "GET").upper()
                path = endpoint.get("path") or "/"
                status = int(endpoint.get("expected_status", endpoint.get("status", 200)))
            else:
                method, path, status = "GET", endpoint, 200
            lines.append(f"    - method: {method}")
            lines.append(f"      path: {path}")
            lines.append(f"      expect_status: {status}")
    if pages:
        lines.append("  pages:")
        for page in pages:
            url = (page.get("url") or page.get("name")) if isinstance(page, dict) else page
            lines.append(f"    - url: {url}")
            lines.append("      expect_status: 200")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "smoke-suite.yml",
        "kind": "smoke_suite",
    }


# ── 10. Checklist UAT (markdown) ──────────────────────────────────────────────
def generate_uat_checklist(spec: dict[str, Any]) -> dict[str, Any]:
    criteria = spec.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        return {"error": "missing_acceptance_criteria"}

    title = str(spec.get("feature") or "Feature")
    lines: list[str] = [f"# UAT Checklist — {title}", "", "## Acceptance Criteria", ""]
    for idx, item in enumerate(criteria):
        if isinstance(item, dict):
            cid = item.get("id")
            text = (
                item.get("description") or item.get("criterion") or item.get("text") or f"critério {idx + 1}"
            )
        else:
            cid, text = None, item
        prefix = f"**{cid}** — " if cid else ""
        lines.append(f"- [ ] {prefix}{text}")
    lines.append("")
    lines.append("## Sign-off")
    lines.append("")
    lines.append("- [ ] Aprovado pelo negócio")
    lines.append("- [ ] Aprovado pelo QA")
    lines.append("")

    return {"artifact": "\n".join(lines), "filename": "uat-checklist.md", "kind": "uat_checklist"}


# ── 11. Config de quality gate (JSON) ─────────────────────────────────────────
def generate_quality_gate(spec: dict[str, Any]) -> dict[str, Any]:
    metrics = spec.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return {"error": "missing_metrics"}

    gate: dict[str, Any] = {
        "quality_gate": {
            "enabled": True,
            "on_failure": str(spec.get("on_failure") or "block"),
            "thresholds": {key: metrics[key] for key in sorted(metrics)},
        }
    }
    service = spec.get("service")
    if service:
        gate["quality_gate"]["service"] = service

    artifact = json.dumps(gate, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return {"artifact": artifact, "filename": "quality-gate.json", "kind": "quality_gate_config"}
