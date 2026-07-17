"""Geradores determinísticos de frontend (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``/``update_*``), estas tools NÃO
tocam o ``FrontendStore``: são funções puras ``spec: dict -> dict`` que fazem
SCAFFOLD de artefatos de UI (componentes React/TSX, páginas Next.js, hooks,
formulários validados, tipos TS, stories do Storybook, clientes de API, mapas de
variantes, wireframes ASCII e design tokens) por template de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str|dict>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. Chaves de dicionários de entrada (props/args/palette/…) são
renderizadas em ordem alfabética estável; listas ordenadas pela spec (props/fields/
endpoints/variants/blocks) preservam a ordem dada — de modo que a MESMA spec produza
SEMPRE o MESMO output. Só depende da stdlib → importável/testável sem banco.

O gerador FORMATA/scaffolda a spec fornecida: quando um conteúdo não vem na spec,
usa defaults/placeholders sensatos (``TODO``/tipos ``unknown``) — NÃO inventa
conteúdo de domínio (isso é papel do agente).
"""

from __future__ import annotations

import json
import re
from typing import Any

# ── Constantes de suporte ─────────────────────────────────────────────────────
REACT_HOOKS = frozenset(
    {
        "useState",
        "useEffect",
        "useRef",
        "useMemo",
        "useCallback",
        "useContext",
        "useReducer",
        "useLayoutEffect",
        "useImperativeHandle",
        "useDebugValue",
        "useId",
        "useTransition",
        "useDeferredValue",
        "useSyncExternalStore",
    }
)
_HOOK_BODIES: dict[str, str] = {
    "useState": "const [state, setState] = useState<unknown>(null);",
    "useEffect": "useEffect(() => {\n    // TODO: side effect\n  }, []);",
    "useRef": "const ref = useRef(null);",
    "useMemo": "const memoized = useMemo(() => null, []);",
    "useCallback": "const callback = useCallback(() => {}, []);",
    "useContext": "const ctx = useContext(Context);",
    "useReducer": "const [reducerState, dispatch] = useReducer(reducer, {});",
}
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


# ── Helpers de nomeação (determinísticos) ─────────────────────────────────────
def _pascal(text: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", str(text))
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "Component"


def _camel(text: str) -> str:
    pas = _pascal(text)
    return pas[:1].lower() + pas[1:]


def _slug(text: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", str(text).lower())
    return "-".join(p for p in parts if p) or "item"


# ── Helpers de normalização de spec ───────────────────────────────────────────
def _norm_props(raw: Any) -> list[tuple[str, str, bool]]:
    """Normaliza props/params: item pode ser ``str`` (só o nome) ou ``dict``
    ``{name, type?, optional?}``. Retorna ``[(name, type, optional)]``."""
    out: list[tuple[str, str, bool]] = []
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            out.append((name, str(item.get("type") or "unknown"), bool(item.get("optional", False))))
        else:
            name = str(item).strip()
            if name:
                out.append((name, "unknown", False))
    return out


def _norm_named(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    """Normaliza uma lista nomeada (variants/blocks): item ``str`` ou ``dict``
    ``{name, ...extra}``. Retorna ``[(name, extra)]`` preservando a ordem."""
    out: list[tuple[str, dict[str, Any]]] = []
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if name:
                out.append((name, item))
        else:
            name = str(item).strip()
            if name:
                out.append((name, {}))
    return out


# ── Helpers de renderização TS (objeto com chaves ORDENADAS) ──────────────────
def _ts_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _ts_object(data: dict[str, Any], indent: int) -> str:
    """Renderiza um objeto TS ``{ chave: escalar }`` com chaves ordenadas."""
    if not data:
        return "{}"
    pad = " " * indent
    close = " " * max(indent - 2, 0)
    lines = ["{"]
    lines += [f"{pad}{key}: {_ts_scalar(data[key])}," for key in sorted(data)]
    lines.append(close + "}")
    return "\n".join(lines)


def _int_arg(rule: str, default: int = 0) -> int:
    digits = re.search(r"-?\d+", rule.split(":", 1)[1] if ":" in rule else "")
    return int(digits.group()) if digits else default


# ── 1. Componente React (TSX) ─────────────────────────────────────────────────
def generate_react_component(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name", "")).strip()
    if not name:
        return {"error": "missing_name"}
    comp = _pascal(name)
    props = _norm_props(spec.get("props"))
    hooks = [str(h).strip() for h in (spec.get("hooks") or []) if str(h).strip()]
    react_hooks = list(dict.fromkeys(h for h in hooks if h in REACT_HOOKS))
    custom_hooks = list(dict.fromkeys(h for h in hooks if h not in REACT_HOOKS))

    if react_hooks:
        react_import = f'import React, {{ {", ".join(react_hooks)} }} from "react";'
    else:
        react_import = 'import React from "react";'

    lines: list[str] = [react_import]
    for hook in custom_hooks:
        lines.append(f'// import {{ {hook} }} from "./hooks/{hook}";')
    lines.append("")

    if props:
        iface = f"{comp}Props"
        lines.append(f"export interface {iface} {{")
        for pname, ptype, optional in props:
            lines.append(f"  {pname}{'?' if optional else ''}: {ptype};")
        lines.append("}")
        lines.append("")
        destructure = "{ " + ", ".join(p[0] for p in props) + " }"
        lines.append(f"export function {comp}({destructure}: {iface}): JSX.Element {{")
    else:
        lines.append(f"export function {comp}(): JSX.Element {{")

    for hook in hooks:
        body = _HOOK_BODIES.get(hook, f"const {_camel(hook)}Value = {hook}();")
        lines.append(f"  {body}")
    lines += [
        "  return (",
        f'    <div className="{_slug(comp)}">',
        f"      {{/* TODO: implement {comp} */}}",
        "    </div>",
        "  );",
        "}",
        "",
        f"export default {comp};",
    ]
    return {"artifact": "\n".join(lines) + "\n", "filename": f"{comp}.tsx", "kind": "react_component"}


# ── 2. Página Next.js (app router) ────────────────────────────────────────────
def _route_component(route: str) -> str:
    parts = [re.sub(r"[\[\]().]", "", seg) for seg in re.split(r"/+", str(route)) if seg]
    base = "".join(_pascal(seg) for seg in parts if seg) or "Home"
    return f"{base}Page"


def _route_path(route: str) -> str:
    parts = [seg for seg in re.split(r"/+", str(route)) if seg]
    if not parts:
        return "app/page.tsx"
    return "app/" + "/".join(parts) + "/page.tsx"


def generate_nextjs_page(spec: dict[str, Any]) -> dict[str, Any]:
    route = str(spec.get("route", "")).strip()
    if not route:
        return {"error": "missing_route"}
    comp = _route_component(route)
    title = str(spec.get("title") or _pascal(route.strip("/") or "Home"))
    sections = [str(s).strip() for s in (spec.get("sections") or []) if str(s).strip()]

    lines = [
        'import React from "react";',
        "",
        "export const metadata = {",
        f"  title: {json.dumps(title)},",
        "};",
        "",
        f"export default function {comp}(): JSX.Element {{",
        "  return (",
        f'    <main className="{_slug(comp)}">',
        f"      <h1>{title}</h1>",
    ]
    if sections:
        for section in sections:
            lines.append(f'      <section className="{_slug(section)}">{{/* TODO: {section} */}}</section>')
    else:
        lines.append("      {/* TODO: page content */}")
    lines += ["    </main>", "  );", "}"]
    return {"artifact": "\n".join(lines) + "\n", "filename": _route_path(route), "kind": "nextjs_page"}


# ── 3. Custom hook (React) ────────────────────────────────────────────────────
def generate_custom_hook(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name", "")).strip()
    if not name:
        return {"error": "missing_name"}
    if not name.startswith("use"):
        return {"error": "invalid_hook_name", "name": name}
    params = _norm_props(spec.get("params"))
    returns = str(spec.get("returns") or "void").strip() or "void"
    param_sig = ", ".join(f"{pname}: {ptype}" for pname, ptype, _ in params)

    lines = [
        'import { useState } from "react";',
        "",
        f"export function {name}({param_sig}): {returns} {{",
        "  const [state, setState] = useState<unknown>(undefined);",
        f"  // TODO: implement {name}",
    ]
    if returns == "void":
        lines.append("  void state;")
        lines.append("  void setState;")
    else:
        lines.append(f"  return state as unknown as {returns};")
    lines.append("}")
    return {"artifact": "\n".join(lines) + "\n", "filename": f"{name}.ts", "kind": "hook"}


# ── 4. Formulário com validação (react-hook-form + zod) ───────────────────────
_INPUT_TYPES = {"email": "email", "password": "password", "number": "number", "tel": "tel", "url": "url"}


def _zod_for_field(ftype: str, rules: list[Any]) -> str:
    kind = str(ftype or "text").lower()
    if kind in ("number", "integer"):
        base = "z.number()"
    elif kind in ("checkbox", "boolean", "bool"):
        base = "z.boolean()"
    else:
        base = "z.string()"
    chain = ""
    normalized = sorted(str(r).strip().lower() for r in rules)
    required = "required" in normalized
    for rule in normalized:
        if rule == "required" and base == "z.string()":
            chain += ".min(1)"
        elif rule == "email":
            chain += ".email()"
        elif rule == "url":
            chain += ".url()"
        elif rule.startswith("min:"):
            chain += f".min({_int_arg(rule)})"
        elif rule.startswith("max:"):
            chain += f".max({_int_arg(rule)})"
    if not required:
        chain += ".optional()"
    return base + chain


def generate_form_with_validation(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name", "")).strip()
    if not name:
        return {"error": "missing_name"}
    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields:
        return {"error": "missing_fields"}

    base = _pascal(name)
    comp = base if base.endswith("Form") else f"{base}Form"
    schema_var = f"{_camel(name)}Schema"
    values_type = f"{base}Values"

    schema_lines = [f"const {schema_var} = z.object({{"]
    input_rows: list[str] = []
    for field in fields:
        if not isinstance(field, dict):
            return {"error": "field_not_object", "field": field}
        fname = str(field.get("name", "")).strip()
        if not fname:
            return {"error": "field_missing_name", "field": field}
        ftype = str(field.get("type") or "text")
        rules = field.get("rules") or []
        rules = rules if isinstance(rules, list) else [rules]
        schema_lines.append(f"  {fname}: {_zod_for_field(ftype, rules)},")
        input_type = _INPUT_TYPES.get(ftype.lower(), "text")
        input_rows += [
            "      <label>",
            f"        {_pascal(fname)}",
            f'        <input {{...register("{fname}")}} type="{input_type}" />',
            "      </label>",
            f"      {{errors.{fname} && <span>{{errors.{fname}.message}}</span>}}",
        ]
    schema_lines.append("});")

    lines = [
        'import React from "react";',
        'import { useForm } from "react-hook-form";',
        'import { z } from "zod";',
        'import { zodResolver } from "@hookform/resolvers/zod";',
        "",
        *schema_lines,
        "",
        f"type {values_type} = z.infer<typeof {schema_var}>;",
        "",
        f"export function {comp}(): JSX.Element {{",
        "  const {",
        "    register,",
        "    handleSubmit,",
        "    formState: { errors },",
        f"  }} = useForm<{values_type}>({{ resolver: zodResolver({schema_var}) }});",
        "",
        f"  const onSubmit = (values: {values_type}) => {{",
        "    // TODO: handle submit",
        "    void values;",
        "  };",
        "",
        "  return (",
        "    <form onSubmit={handleSubmit(onSubmit)}>",
        *input_rows,
        '      <button type="submit">Submit</button>',
        "    </form>",
        "  );",
        "}",
    ]
    return {"artifact": "\n".join(lines) + "\n", "filename": f"{comp}.tsx", "kind": "form"}


# ── 5. Tipos TypeScript ───────────────────────────────────────────────────────
def generate_typescript_types(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name", "")).strip()
    if not name:
        return {"error": "missing_name"}
    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields:
        return {"error": "missing_fields"}

    iface = _pascal(name)
    lines = [f"export interface {iface} {{"]
    for field in fields:
        if not isinstance(field, dict):
            return {"error": "field_not_object", "field": field}
        fname = str(field.get("name", "")).strip()
        if not fname:
            return {"error": "field_missing_name", "field": field}
        ftype = str(field.get("type") or "unknown")
        opt = "?" if field.get("optional") else ""
        lines.append(f"  {fname}{opt}: {ftype};")
    lines.append("}")
    return {"artifact": "\n".join(lines) + "\n", "filename": f"{iface}.ts", "kind": "typescript_types"}


# ── 6. Storybook story (CSF3) ─────────────────────────────────────────────────
def generate_storybook_story(spec: dict[str, Any]) -> dict[str, Any]:
    component = str(spec.get("component", "")).strip()
    if not component:
        return {"error": "missing_component"}
    comp = _pascal(component)
    variants = _norm_named(spec.get("variants")) or [("Default", {})]

    lines = [
        'import type { Meta, StoryObj } from "@storybook/react";',
        f'import {{ {comp} }} from "./{comp}";',
        "",
        f"const meta: Meta<typeof {comp}> = {{",
        f'  title: "Components/{comp}",',
        f"  component: {comp},",
        "};",
        "",
        "export default meta;",
        "",
        f"type Story = StoryObj<typeof {comp}>;",
    ]
    for vname, extra in variants:
        raw_args = extra.get("args")
        args = raw_args if isinstance(raw_args, dict) else {}
        lines += [
            "",
            f"export const {_pascal(vname)}: Story = {{",
            f"  args: {_ts_object(args, 4)},",
            "};",
        ]
    return {"artifact": "\n".join(lines) + "\n", "filename": f"{comp}.stories.tsx", "kind": "storybook_story"}


# ── 7. Cliente de API (fetch TS) ──────────────────────────────────────────────
def generate_api_service(spec: dict[str, Any]) -> dict[str, Any]:
    base = str(spec.get("base", "")).strip()
    if not base:
        return {"error": "missing_base"}
    endpoints = spec.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        return {"error": "missing_endpoints"}

    lines = [
        f"const BASE_URL = {json.dumps(base)};",
        "",
        "async function request<T>(path: string, init?: RequestInit): Promise<T> {",
        "  const response = await fetch(`${BASE_URL}${path}`, {",
        '    headers: { "Content-Type": "application/json" },',
        "    ...init,",
        "  });",
        "  if (!response.ok) {",
        "    throw new Error(`Request failed: ${response.status}`);",
        "  }",
        "  return (await response.json()) as T;",
        "}",
        "",
        "export const apiService = {",
    ]
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            return {"error": "endpoint_not_object", "endpoint": endpoint}
        ename = str(endpoint.get("name", "")).strip()
        if not ename:
            return {"error": "endpoint_missing_name", "endpoint": endpoint}
        method = str(endpoint.get("method") or "GET").upper()
        path = str(endpoint.get("path") or "/")
        fn = _camel(ename)
        if method in _BODY_METHODS:
            lines.append(f"  {fn}: (body?: unknown): Promise<unknown> =>")
            lines.append(
                f"    request({json.dumps(path)}, "
                f"{{ method: {json.dumps(method)}, body: JSON.stringify(body) }}),"
            )
        else:
            lines.append(
                f"  {fn}: (): Promise<unknown> => "
                f"request({json.dumps(path)}, {{ method: {json.dumps(method)} }}),"
            )
    lines.append("};")
    return {"artifact": "\n".join(lines) + "\n", "filename": "apiService.ts", "kind": "api_service"}


# ── 8. Mapa de variantes (class-variance-authority) ───────────────────────────
def generate_component_variants(spec: dict[str, Any]) -> dict[str, Any]:
    base = str(spec.get("base", "")).strip()
    if not base:
        return {"error": "missing_base"}
    variants = _norm_named(spec.get("variants"))
    if not variants:
        return {"error": "missing_variants"}

    base_class = _slug(base)
    export_name = f"{_camel(base)}Variants"
    default_variant = _camel(variants[0][0])

    lines = [
        'import { cva } from "class-variance-authority";',
        "",
        f"export const {export_name} = cva({json.dumps(base_class)}, {{",
        "  variants: {",
        "    variant: {",
    ]
    for vname, extra in variants:
        raw = extra.get("classes")
        classes = str(raw) if raw else f"{base_class}--{_slug(vname)}"
        lines.append(f"      {_camel(vname)}: {json.dumps(classes)},")
    lines += [
        "    },",
        "  },",
        "  defaultVariants: {",
        f"    variant: {json.dumps(default_variant)},",
        "  },",
        "});",
    ]
    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"{export_name}.ts",
        "kind": "component_variants",
    }


# ── 9. Wireframe ASCII ────────────────────────────────────────────────────────
def generate_wireframe(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec.get("title", "")).strip()
    if not title:
        return {"error": "missing_title"}
    blocks = _norm_named(spec.get("blocks"))
    if not blocks:
        return {"error": "missing_blocks"}

    try:
        width = int(spec.get("width", 44))
    except (TypeError, ValueError):
        width = 44
    width = max(width, len(title) + 4, 20)
    inner = width - 4
    border = "+" + "-" * (width - 2) + "+"

    def _row(text: str) -> str:
        clipped = str(text)[:inner]
        return "| " + clipped + " " * (inner - len(clipped)) + " |"

    lines = [border, _row(title), border]
    for bname, extra in blocks:
        try:
            height = max(1, int(extra.get("height", 1)))
        except (TypeError, ValueError):
            height = 1
        lines.append(_row(bname))
        lines += [_row("") for _ in range(height - 1)]
        lines.append(border)
    return {"artifact": "\n".join(lines) + "\n", "filename": f"{_slug(title)}.txt", "kind": "wireframe"}


# ── 10. Design tokens (CSS custom properties + JSON) ──────────────────────────
def create_design_tokens(spec: dict[str, Any]) -> dict[str, Any]:
    palette = spec.get("palette")
    if not isinstance(palette, dict) or not palette:
        return {"error": "missing_palette"}
    spacing = spec.get("spacing")
    if not isinstance(spacing, dict) or not spacing:
        spacing = {"sm": "0.25rem", "md": "0.5rem", "lg": "1rem"}

    css_lines = [":root {"]
    css_lines += [f"  --color-{_slug(key)}: {palette[key]};" for key in sorted(palette)]
    css_lines += [f"  --spacing-{_slug(key)}: {spacing[key]};" for key in sorted(spacing)]
    css_lines.append("}")
    css = "\n".join(css_lines) + "\n"

    tokens = {
        "color": {str(key): palette[key] for key in palette},
        "spacing": {str(key): spacing[key] for key in spacing},
    }
    tokens_json = json.dumps(tokens, sort_keys=True, indent=2) + "\n"

    return {
        "artifact": {"design-tokens.css": css, "design-tokens.json": tokens_json},
        "filename": "design-tokens",
        "kind": "design_tokens",
    }
