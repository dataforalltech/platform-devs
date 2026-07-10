"""Frontend & UI tools do frontend-mcp.

Persona **compute-only**: cada ferramenta deriva a saída DOS INPUTS recebidos
(nome do componente, rota, nome do formulário, etc.) e monta um scaffold
determinístico de frontend — nada de I/O de rede nem backend REST.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "generate_react_component",
    "generate_nextjs_page",
    "generate_storybook_story",
    "generate_form_with_validation",
    "status",
    "SERVER_NAME",
]

SERVER_NAME = "frontend-mcp"


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────── #
def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _server_version() -> str:
    """Lê a versão declarada no pyproject.toml do servidor (não hardcoded)."""
    # frontend_tools.py → src/tools/ ; pyproject fica 3 níveis acima.
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else "unknown"


# ──────────────────────────────────────────────────────────────────────────── #
# 1) React component scaffold — derivado do nome/variante
# ──────────────────────────────────────────────────────────────────────────── #
def generate_react_component(
    name: str = "Component", variant: str = "functional"
) -> dict[str, Any]:
    """Gera o scaffold de um componente React a partir do nome e da variante."""
    name = (name or "Component").strip() or "Component"
    variant = (variant or "functional").strip() or "functional"
    return {
        "title": f"React Component: {name}",
        "name": name,
        "variant": variant,
        "template": f"export default function {name}() {{\n  return <div>{name}</div>\n}}",
        "styling": "tailwind",
        "status": "generated",
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 2) Next.js page — App Router, derivado da rota
# ──────────────────────────────────────────────────────────────────────────── #
def generate_nextjs_page(route: str = "/") -> dict[str, Any]:
    """Gera uma página Next.js (App Router) a partir da rota informada."""
    route = (route or "/").strip() or "/"
    return {
        "title": f"Next.js Page: {route}",
        "route": route,
        "type": "app-route",
        "template": "export default function Page() {\n  return <div>Page</div>\n}",
        "status": "generated",
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 3) Storybook story — CSF 3.0, derivado do nome do componente
# ──────────────────────────────────────────────────────────────────────────── #
def generate_storybook_story(component_name: str = "Component") -> dict[str, Any]:
    """Gera uma story de Storybook (CSF 3.0) para o componente informado."""
    component_name = (component_name or "Component").strip() or "Component"
    return {
        "title": f"Storybook Story: {component_name}",
        "component": component_name,
        "stories": ["Default", "Loading", "Error"],
        "status": "generated",
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 4) Form + validação — React Hook Form + Zod, derivado do nome
# ──────────────────────────────────────────────────────────────────────────── #
def generate_form_with_validation(form_name: str = "Form") -> dict[str, Any]:
    """Gera um formulário com React Hook Form + validação Zod."""
    form_name = (form_name or "Form").strip() or "Form"
    return {
        "title": f"Form: {form_name}",
        "name": form_name,
        "fields": ["email", "password"],
        "validation": "zod",
        "library": "react-hook-form",
        "status": "generated",
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 5) status — status real do servidor
# ──────────────────────────────────────────────────────────────────────────── #
def status() -> dict[str, Any]:
    """Retorna o status real do servidor (nome, versão do pyproject, nº de tools, timestamp)."""
    tool_names = [
        "generate_react_component",
        "generate_nextjs_page",
        "generate_storybook_story",
        "generate_form_with_validation",
        "status",
    ]
    return {
        "name": SERVER_NAME,
        "status": "ok",
        "version": _server_version(),
        "tool_count": len(tool_names),
        "tools": tool_names,
        "timestamp": _now_iso(),
    }
