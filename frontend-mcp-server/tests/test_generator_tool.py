"""Unidade dos geradores determinísticos de frontend (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
mais um guard de spec inválida e um teste global de DETERMINISMO (mesma spec chamada
2x → output idêntico)."""

from __future__ import annotations

import pytest

from src.tools.generator_tool import (
    create_design_tokens,
    generate_api_service,
    generate_component_variants,
    generate_custom_hook,
    generate_form_with_validation,
    generate_nextjs_page,
    generate_react_component,
    generate_storybook_story,
    generate_typescript_types,
    generate_wireframe,
)

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
REACT_SPEC = {
    "name": "user-card",
    "props": [
        {"name": "label", "type": "string"},
        {"name": "onClick", "type": "() => void", "optional": True},
    ],
    "hooks": ["useState", "useEffect", "useAuth"],
}
NEXTJS_SPEC = {
    "route": "/dashboard/reports",
    "title": "Reports",
    "sections": ["Hero", "Table"],
}
HOOK_SPEC = {
    "name": "useCounter",
    "params": [{"name": "initial", "type": "number"}],
    "returns": "number",
}
FORM_SPEC = {
    "name": "login",
    "fields": [
        {"name": "email", "type": "email", "rules": ["required", "email"]},
        {"name": "password", "type": "password", "rules": ["required", "min:8"]},
    ],
}
TYPES_SPEC = {
    "name": "user",
    "fields": [
        {"name": "id", "type": "number"},
        {"name": "name", "type": "string"},
        {"name": "email", "type": "string", "optional": True},
    ],
}
STORY_SPEC = {
    "component": "Button",
    "variants": [
        {"name": "Primary", "args": {"variant": "primary", "disabled": False}},
        "Secondary",
    ],
}
API_SPEC = {
    "base": "https://api.example.com",
    "endpoints": [
        {"name": "getUser", "method": "GET", "path": "/users/1"},
        {"name": "createUser", "method": "POST", "path": "/users"},
    ],
}
VARIANTS_SPEC = {
    "base": "Button",
    "variants": [{"name": "primary"}, {"name": "secondary", "classes": "btn-secondary"}],
}
WIREFRAME_SPEC = {
    "title": "Dashboard",
    "blocks": ["Header", {"name": "Content", "height": 2}, "Footer"],
}
TOKENS_SPEC = {
    "palette": {"primary": "#0055ff", "danger": "#ff0000"},
    "spacing": {"sm": "4px", "lg": "16px"},
}


# ── 1. React component ────────────────────────────────────────────────────────
def test_generate_react_component_markers():
    out = generate_react_component(REACT_SPEC)
    art = out["artifact"]
    assert out["kind"] == "react_component"
    assert out["filename"] == "UserCard.tsx"
    assert "export function UserCard(" in art
    assert "export interface UserCardProps {" in art
    assert "onClick?: () => void;" in art
    # hooks React vão no import nomeado; hook custom vira comentário de import
    assert 'import React, { useState, useEffect } from "react";' in art
    assert "// import { useAuth }" in art
    assert "export default UserCard;" in art


def test_generate_react_component_requires_name():
    assert generate_react_component({"props": []})["error"] == "missing_name"


# ── 2. Next.js page ───────────────────────────────────────────────────────────
def test_generate_nextjs_page_markers():
    out = generate_nextjs_page(NEXTJS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "nextjs_page"
    assert out["filename"] == "app/dashboard/reports/page.tsx"
    assert "export default function DashboardReportsPage()" in art
    assert 'title: "Reports"' in art
    assert "<section" in art and "Hero" in art


def test_generate_nextjs_page_requires_route():
    assert generate_nextjs_page({"title": "x"})["error"] == "missing_route"


# ── 3. Custom hook ────────────────────────────────────────────────────────────
def test_generate_custom_hook_markers():
    out = generate_custom_hook(HOOK_SPEC)
    art = out["artifact"]
    assert out["kind"] == "hook"
    assert out["filename"] == "useCounter.ts"
    assert "export function useCounter(initial: number): number {" in art
    assert "return state as unknown as number;" in art


def test_generate_custom_hook_rejects_non_use_prefix():
    assert generate_custom_hook({"name": "counter"})["error"] == "invalid_hook_name"


# ── 4. Form with validation ───────────────────────────────────────────────────
def test_generate_form_with_validation_markers():
    out = generate_form_with_validation(FORM_SPEC)
    art = out["artifact"]
    assert out["kind"] == "form"
    assert out["filename"] == "LoginForm.tsx"
    assert 'import { z } from "zod";' in art
    assert "const loginSchema = z.object({" in art
    assert "email: z.string().email().min(1)" in art
    assert "password: z.string().min(8).min(1)" in art
    assert "zodResolver(loginSchema)" in art
    assert '<input {...register("email")} type="email" />' in art


def test_generate_form_requires_fields():
    assert generate_form_with_validation({"name": "x", "fields": []})["error"] == "missing_fields"


# ── 5. TypeScript types ───────────────────────────────────────────────────────
def test_generate_typescript_types_markers():
    out = generate_typescript_types(TYPES_SPEC)
    art = out["artifact"]
    assert out["kind"] == "typescript_types"
    assert out["filename"] == "User.ts"
    assert "export interface User {" in art
    assert "id: number;" in art
    assert "email?: string;" in art


def test_generate_typescript_types_requires_fields():
    assert generate_typescript_types({"name": "x"})["error"] == "missing_fields"


# ── 6. Storybook story ────────────────────────────────────────────────────────
def test_generate_storybook_story_markers():
    out = generate_storybook_story(STORY_SPEC)
    art = out["artifact"]
    assert out["kind"] == "storybook_story"
    assert out["filename"] == "Button.stories.tsx"
    assert "const meta: Meta<typeof Button>" in art
    assert "export const Primary: Story = {" in art
    assert "export const Secondary: Story = {" in art
    # args com chaves ordenadas (disabled antes de variant)
    assert "disabled: false," in art
    assert 'variant: "primary",' in art


def test_generate_storybook_story_requires_component():
    assert generate_storybook_story({"variants": []})["error"] == "missing_component"


# ── 7. API service ────────────────────────────────────────────────────────────
def test_generate_api_service_markers():
    out = generate_api_service(API_SPEC)
    art = out["artifact"]
    assert out["kind"] == "api_service"
    assert out["filename"] == "apiService.ts"
    assert 'const BASE_URL = "https://api.example.com";' in art
    assert "export const apiService = {" in art
    assert 'getUser: (): Promise<unknown> => request("/users/1", { method: "GET" }),' in art
    assert "createUser: (body?: unknown): Promise<unknown> =>" in art
    assert "body: JSON.stringify(body)" in art


def test_generate_api_service_requires_endpoints():
    assert generate_api_service({"base": "http://x"})["error"] == "missing_endpoints"


# ── 8. Component variants ─────────────────────────────────────────────────────
def test_generate_component_variants_markers():
    out = generate_component_variants(VARIANTS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "component_variants"
    assert out["filename"] == "buttonVariants.ts"
    assert "export const buttonVariants = cva(" in art
    assert 'primary: "button--primary",' in art
    assert 'secondary: "btn-secondary",' in art
    assert 'variant: "primary",' in art  # defaultVariants = primeira variante


def test_generate_component_variants_requires_variants():
    assert generate_component_variants({"base": "Button"})["error"] == "missing_variants"


# ── 9. Wireframe ──────────────────────────────────────────────────────────────
def test_generate_wireframe_markers():
    out = generate_wireframe(WIREFRAME_SPEC)
    art = out["artifact"]
    assert out["kind"] == "wireframe"
    assert out["filename"] == "dashboard.txt"
    assert "| Dashboard" in art
    assert "| Header" in art
    assert "| Content" in art
    assert "| Footer" in art
    # todas as linhas têm a mesma largura (quadro retangular)
    widths = {len(line) for line in art.splitlines()}
    assert len(widths) == 1


def test_generate_wireframe_requires_blocks():
    assert generate_wireframe({"title": "x"})["error"] == "missing_blocks"


# ── 10. Design tokens ─────────────────────────────────────────────────────────
def test_create_design_tokens_markers():
    out = create_design_tokens(TOKENS_SPEC)
    art = out["artifact"]
    assert out["kind"] == "design_tokens"
    assert isinstance(art, dict)
    assert "design-tokens.css" in art and "design-tokens.json" in art
    css = art["design-tokens.css"]
    assert ":root {" in css
    # chaves ordenadas: danger antes de primary
    assert css.index("--color-danger") < css.index("--color-primary")
    assert "--spacing-lg: 16px;" in css
    assert '"color"' in art["design-tokens.json"]


def test_create_design_tokens_requires_palette():
    assert create_design_tokens({"spacing": {"sm": "4px"}})["error"] == "missing_palette"


def test_create_design_tokens_defaults_spacing():
    out = create_design_tokens({"palette": {"primary": "#000"}})
    assert "--spacing-md: 0.5rem;" in out["artifact"]["design-tokens.css"]


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_react_component, REACT_SPEC),
        (generate_nextjs_page, NEXTJS_SPEC),
        (generate_custom_hook, HOOK_SPEC),
        (generate_form_with_validation, FORM_SPEC),
        (generate_typescript_types, TYPES_SPEC),
        (generate_storybook_story, STORY_SPEC),
        (generate_api_service, API_SPEC),
        (generate_component_variants, VARIANTS_SPEC),
        (generate_wireframe, WIREFRAME_SPEC),
        (create_design_tokens, TOKENS_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    import copy

    assert fn(copy.deepcopy(spec)) == fn(copy.deepcopy(spec))


def test_token_key_ordering_is_stable_regardless_of_input_order():
    # palettes com mesma composição mas ordens de inserção diferentes → mesmo output.
    a = create_design_tokens({"palette": {"a": "#1", "b": "#2"}, "spacing": {"sm": "4px"}})
    b = create_design_tokens({"palette": {"b": "#2", "a": "#1"}, "spacing": {"sm": "4px"}})
    assert a == b
