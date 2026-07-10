"""Testes das tools do frontend-mcp-server.

Foco: a saída deve ser DERIVADA DOS INPUTS (o nome/rota fornecido reaparece na
saída) e os defaults devem ser aplicados quando o input vem vazio.
"""

from __future__ import annotations

import re

from src.tools.frontend_tools import (
    generate_form_with_validation,
    generate_nextjs_page,
    generate_react_component,
    generate_storybook_story,
    status,
)


# ── generate_react_component ────────────────────────────────────────────────── #
def test_react_component_uses_custom_name_and_variant():
    result = generate_react_component(name="UserCard", variant="class")
    assert result["name"] == "UserCard"
    assert result["variant"] == "class"
    # O nome custom aparece no template gerado, não uma constante.
    assert "function UserCard()" in result["template"]
    assert "<div>UserCard</div>" in result["template"]
    assert result["styling"] == "tailwind"
    assert result["status"] == "generated"


def test_react_component_defaults_when_blank():
    result = generate_react_component(name="   ", variant="")
    assert result["name"] == "Component"
    assert result["variant"] == "functional"
    assert "function Component()" in result["template"]


# ── generate_nextjs_page ────────────────────────────────────────────────────── #
def test_nextjs_page_reflects_route():
    result = generate_nextjs_page(route="/settings/profile")
    assert result["route"] == "/settings/profile"
    assert result["title"] == "Next.js Page: /settings/profile"
    assert result["type"] == "app-route"
    assert result["status"] == "generated"


def test_nextjs_page_defaults_root_route():
    result = generate_nextjs_page(route="")
    assert result["route"] == "/"


# ── generate_storybook_story ────────────────────────────────────────────────── #
def test_storybook_story_targets_component():
    result = generate_storybook_story(component_name="PrimaryButton")
    assert result["component"] == "PrimaryButton"
    assert result["title"] == "Storybook Story: PrimaryButton"
    # Stories padrão do CSF 3.0 presentes.
    assert result["stories"] == ["Default", "Loading", "Error"]
    assert result["status"] == "generated"


def test_storybook_story_defaults_when_blank():
    result = generate_storybook_story(component_name="")
    assert result["component"] == "Component"


# ── generate_form_with_validation ───────────────────────────────────────────── #
def test_form_reflects_name_and_stack():
    result = generate_form_with_validation(form_name="SignupForm")
    assert result["name"] == "SignupForm"
    assert result["title"] == "Form: SignupForm"
    assert result["validation"] == "zod"
    assert result["library"] == "react-hook-form"
    assert result["fields"] == ["email", "password"]
    assert result["status"] == "generated"


def test_form_defaults_when_blank():
    result = generate_form_with_validation(form_name="   ")
    assert result["name"] == "Form"


# ── status ──────────────────────────────────────────────────────────────────── #
def test_status_reports_real_server_metadata():
    result = status()
    assert result["name"] == "frontend-mcp"
    assert result["status"] == "ok"
    assert result["tool_count"] == 5
    # Versão vem do pyproject.toml, não hardcoded ('unknown' só se ilegível).
    assert re.match(r"^\d+\.\d+\.\d+$", result["version"]), result["version"]
    # Timestamp ISO-8601 presente.
    assert "T" in result["timestamp"]


def test_status_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as fh:
        declared = tomllib.load(fh)["project"]["version"]
    assert status()["version"] == declared
