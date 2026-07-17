from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).parent.parent / "knowledge" / "templates"

# Hardcoded catalogue with metadata for each template
_TEMPLATE_CATALOGUE: list[dict[str, Any]] = [
    {
        "name": "README",
        "file": "README.md",
        "description": "Template padrão de README para serviços da plataforma",
        "variables": ["service_name", "description", "registry", "year"],
        "use_case": "Documentação inicial de um novo serviço",
    },
    {
        "name": "CHANGELOG",
        "file": "CHANGELOG.md",
        "description": "Template de changelog no formato Keep a Changelog",
        "variables": ["date", "service_name"],
        "use_case": "Registro de mudanças por versão seguindo semver",
    },
    {
        "name": "ADR",
        "file": "ADR.md",
        "description": "Template de Architecture Decision Record (ADR)",
        "variables": ["number", "title", "date"],
        "use_case": "Documentar decisões arquiteturais com contexto e consequências",
    },
    {
        "name": "AGENTS",
        "file": "AGENTS.md",
        "description": "Template de política para agentes de IA no repositório",
        "variables": ["owner", "slack_channel"],
        "use_case": "Definir regras e diretrizes para agentes de IA atuarem no repo",
    },
    {
        "name": "RUNBOOK",
        "file": "RUNBOOK.md",
        "description": "Template de runbook operacional para serviços em produção",
        "variables": [
            "service_name",
            "host",
            "port",
            "version",
            "container_name",
            "previous_version",
            "oncall",
            "slack_channel",
            "pagerduty_service",
        ],
        "use_case": "Procedimentos de operação, deploy, restart e troubleshooting",
    },
    {
        "name": "API",
        "file": "API.md",
        "description": "Template de referência de API REST com autenticação e endpoints",
        "variables": ["service_name", "base_url", "version"],
        "use_case": "Documentar endpoints, parâmetros, exemplos e códigos de erro de uma API REST",
    },
]

_TEMPLATE_MAP = {t["name"]: t for t in _TEMPLATE_CATALOGUE}


def list_templates() -> dict:
    """
    Retorna catálogo de templates disponíveis em src/knowledge/templates/.
    """
    return {
        "count": len(_TEMPLATE_CATALOGUE),
        "templates": _TEMPLATE_CATALOGUE,
    }


def generate_doc(
    store: Any,
    settings: Any,
    *,
    template_name: str,
    variables: dict[str, str],
    output_path: str | None = None,
) -> dict:
    """
    Gera documento a partir de template com substituição de variáveis.
    """
    if not template_name:
        return {
            "error": "ValidationError",
            "details": "template_name is required",
            "tool": "generate_doc",
        }

    meta = _TEMPLATE_MAP.get(template_name)
    if meta is None:
        available = list(_TEMPLATE_MAP.keys())
        return {
            "error": "ValidationError",
            "details": f"Template '{template_name}' not found. Available: {available}",
            "tool": "generate_doc",
        }

    template_file = _TEMPLATES_DIR / meta["file"]
    if not template_file.exists():
        return {
            "error": "ValidationError",
            "details": f"Template file not found: {template_file}",
            "tool": "generate_doc",
        }

    try:
        content = template_file.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "error": "ValidationError",
            "details": f"Cannot read template: {exc}",
            "tool": "generate_doc",
        }

    # Find all variables in the template
    all_vars = set(re.findall(r"\{\{(\w+)\}\}", content))
    variables_used: list[str] = []
    variables_missing: list[str] = []

    # Substitute variables
    result_content = content
    for var in sorted(all_vars):
        if var in variables:
            result_content = result_content.replace(f"{{{{{var}}}}}", variables[var])
            variables_used.append(var)
        else:
            variables_missing.append(var)

    saved = False
    if output_path:
        try:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result_content, encoding="utf-8")
            saved = True
        except OSError as exc:
            return {
                "error": "ValidationError",
                "details": f"Cannot write output file: {exc}",
                "tool": "generate_doc",
            }

    return {
        "template": template_name,
        "variables_used": sorted(variables_used),
        "variables_missing": sorted(variables_missing),
        "content": result_content,
        "output_path": output_path,
        "saved": saved,
        "char_count": len(result_content),
    }
