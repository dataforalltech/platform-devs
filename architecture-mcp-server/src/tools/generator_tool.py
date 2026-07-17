"""Geradores determinísticos de artefatos de arquitetura (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``), estas tools NÃO tocam o
``ArchitectureStore``: são funções puras ``spec: dict -> dict`` que renderizam
artefatos de arquitetura (diagramas C4 e de sequência em Mermaid, ADRs em Markdown)
por template de string. Elas FORMATAM/scaffoldam a spec fornecida pelo agente — não
inventam conteúdo de domínio (atores, decisões e mensagens vêm sempre do agente).

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str>, "filename": <str>, "kind": <str>}`` em caso de sucesso, ou
``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. Listas preservam a ordem fornecida na spec e ids são derivados
por ``slug`` estável, de modo que a MESMA spec produza SEMPRE o MESMO output byte-a-byte.
Só depende da stdlib + helpers puros → importável/testável sem banco.
"""

from __future__ import annotations

import re
from typing import Any

from ._common import slug

_SIMPLE_TOKEN = re.compile(r"[A-Za-z0-9_]+")

# ── Constantes de suporte ─────────────────────────────────────────────────────
_C4_LEVELS = {
    "context": ("C4Context", "system", "Context"),
    "container": ("C4Container", "container", "Container"),
    "component": ("C4Component", "component", "Component"),
}
# Mapa tipo-de-elemento → (macro Mermaid C4, aceita_technology?).
_C4_MACROS: dict[str, tuple[str, bool]] = {
    "person": ("Person", False),
    "external_person": ("Person_Ext", False),
    "person_ext": ("Person_Ext", False),
    "system": ("System", False),
    "external_system": ("System_Ext", False),
    "system_ext": ("System_Ext", False),
    "system_db": ("SystemDb", False),
    "container": ("Container", True),
    "database": ("ContainerDb", True),
    "container_db": ("ContainerDb", True),
    "queue": ("ContainerQueue", True),
    "component": ("Component", True),
    "component_db": ("ComponentDb", True),
}
# Setas de sequência Mermaid por tipo lógico de mensagem.
_SEQ_ARROWS = {
    "sync": "->>",
    "call": "->>",
    "solid": "->>",
    "async": "-)",
    "return": "-->>",
    "response": "-->>",
    "reply": "-->>",
    "dashed": "-->>",
}


# ── Helpers de renderização (Mermaid/Markdown por string, determinísticos) ─────
def _q(value: Any) -> str:
    """Escala Mermaid entre aspas, escapando aspas duplas internas."""
    return '"{}"'.format(str(value).replace('"', '\\"'))


def _as_lines(value: Any) -> list[str]:
    """Normaliza um bloco (str única, lista ou None) numa lista de linhas não-vazias."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return text.splitlines() if text else []


def _md_block(value: Any, placeholder: str = "TBD") -> str:
    """Renderiza um bloco Markdown: lista vira bullets; str vira parágrafo; vazio → placeholder."""
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value if str(v).strip()]
        return "\n".join(f"- {item}" for item in items) if items else placeholder
    text = str(value).strip() if value is not None else ""
    return text or placeholder


# ── 1. Diagrama C4 (Mermaid) ──────────────────────────────────────────────────
def generate_c4_diagram(spec: dict[str, Any]) -> dict[str, Any]:
    level = str(spec.get("level", "")).strip().lower()
    if level not in _C4_LEVELS:
        return {"error": "unsupported_level", "level": level, "valid": sorted(_C4_LEVELS)}

    elements = spec.get("elements")
    if not isinstance(elements, list) or not elements:
        return {"error": "missing_elements"}

    header, default_type, level_label = _C4_LEVELS[level]
    title = str(spec.get("title") or f"C4 {level_label} Diagram")
    lines: list[str] = [header, f"    title {title}"]

    name_to_id: dict[str, str] = {}
    for raw in elements:
        if isinstance(raw, dict):
            name = str(raw.get("name", "")).strip()
            if not name:
                return {"error": "element_missing_name", "element": raw}
            etype = str(raw.get("type") or default_type).strip().lower()
            tech = str(raw.get("technology", "")).strip()
            desc = str(raw.get("description", "")).strip()
            eid = str(raw.get("id") or slug(name)).strip()
        else:
            name = str(raw).strip()
            if not name:
                return {"error": "element_missing_name", "element": raw}
            etype, tech, desc, eid = default_type, "", "", slug(name)

        macro, has_tech = _C4_MACROS.get(etype, _C4_MACROS[default_type])
        name_to_id[name] = eid
        name_to_id[eid] = eid
        if has_tech:
            lines.append(f"    {macro}({eid}, {_q(name)}, {_q(tech)}, {_q(desc)})")
        else:
            lines.append(f"    {macro}({eid}, {_q(name)}, {_q(desc)})")

    def _resolve(label: str) -> str:
        label = (label or "").strip()
        return name_to_id.get(label, slug(label))

    for raw in spec.get("relations") or []:
        if isinstance(raw, dict):
            src = str(raw.get("from") or raw.get("source", "")).strip()
            tgt = str(raw.get("to") or raw.get("target", "")).strip()
            text = str(raw.get("text") or raw.get("description", "")).strip()
            tech = str(raw.get("technology", "")).strip()
        elif isinstance(raw, str) and "->" in raw:
            src, _, tgt = raw.partition("->")
            src, tgt, text, tech = src.strip(), tgt.strip(), "", ""
        else:
            continue
        if not src or not tgt:
            continue
        sid, tid = _resolve(src), _resolve(tgt)
        if tech:
            lines.append(f"    Rel({sid}, {tid}, {_q(text)}, {_q(tech)})")
        else:
            lines.append(f"    Rel({sid}, {tid}, {_q(text)})")

    return {"artifact": "\n".join(lines) + "\n", "filename": f"c4-{level}.mmd", "kind": "c4_diagram"}


# ── 2. Diagrama de sequência (Mermaid) ────────────────────────────────────────
def generate_sequence_diagram(spec: dict[str, Any]) -> dict[str, Any]:
    messages = spec.get("messages")
    if not isinstance(messages, list) or not messages:
        return {"error": "missing_messages"}

    title = str(spec.get("title") or "Sequence Diagram")
    lines: list[str] = ["sequenceDiagram", f"    title {title}"]

    # Participantes declarados (ordem preservada); mapeia nome de exibição → id do ator.
    declared: dict[str, str] = {}
    order: list[str] = []

    def _declare(name: str, alias: str | None = None) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        if alias and str(alias).strip():
            aid = str(alias).strip()
        elif _SIMPLE_TOKEN.fullmatch(name):
            aid = name  # token simples preserva o nome (e a caixa) como id
        else:
            aid = slug(name)
        if aid not in declared:
            declared[aid] = name
            order.append(aid)
        return aid

    for raw in spec.get("participants") or []:
        if isinstance(raw, dict):
            _declare(str(raw.get("name", "")), raw.get("alias") or raw.get("id"))
        else:
            _declare(str(raw))

    # Endpoints de mensagens que não foram declarados entram implicitamente (placeholder).
    for msg in messages:
        if not isinstance(msg, dict):
            return {"error": "message_not_object", "message": msg}
        src = str(msg.get("from") or msg.get("source", "")).strip()
        tgt = str(msg.get("to") or msg.get("target", "")).strip()
        if not src or not tgt:
            return {"error": "message_missing_endpoint", "message": msg}
        _declare(src)
        _declare(tgt)

    for aid in order:
        name = declared[aid]
        if aid == name:
            lines.append(f"    participant {aid}")
        else:
            lines.append(f"    participant {aid} as {name}")

    for msg in messages:
        src = str(msg.get("from") or msg.get("source", "")).strip()
        tgt = str(msg.get("to") or msg.get("target", "")).strip()
        text = str(msg.get("text") or msg.get("message", "")).strip()
        arrow = _SEQ_ARROWS.get(str(msg.get("type", "")).strip().lower(), "->>")
        sid, tid = _declare(src), _declare(tgt)
        lines.append(f"    {sid}{arrow}{tid}: {text}")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "sequence.mmd",
        "kind": "sequence_diagram",
    }


# ── 3. ADR (Architecture Decision Record — Markdown) ──────────────────────────
def generate_adr(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec.get("title", "")).strip()
    if not title:
        return {"error": "missing_title"}

    status = str(spec.get("status") or "Proposed").strip()
    number = spec.get("number")
    if isinstance(number, bool):
        number = None

    if isinstance(number, int):
        heading = f"# ADR {number:04d}: {title}"
        filename = f"adr-{number:04d}-{slug(title)}.md"
    else:
        heading = f"# ADR: {title}"
        filename = f"adr-{slug(title)}.md"

    parts: list[str] = [
        heading,
        "",
        "## Status",
        "",
        status,
        "",
        "## Context",
        "",
        _md_block(spec.get("context")),
        "",
        "## Decision",
        "",
        _md_block(spec.get("decision")),
        "",
        "## Consequences",
        "",
        _md_block(spec.get("consequences")),
    ]

    alternatives = _as_lines(spec.get("alternatives"))
    if alternatives:
        parts += ["", "## Alternatives Considered", ""]
        parts += [f"- {alt}" for alt in alternatives]

    return {"artifact": "\n".join(parts) + "\n", "filename": filename, "kind": "adr"}


__all__ = ["generate_c4_diagram", "generate_sequence_diagram", "generate_adr"]
