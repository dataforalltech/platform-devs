"""Geradores determinísticos de artefatos de Product Owner (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``), estas tools NÃO tocam o
``ProductOwnerStore``: são funções puras ``spec: dict -> dict`` que FORMATAM/scaffoldam
a spec fornecida em artefatos de PO (épico, breakdown de feature, tasks de Jira,
release notes, user story e checklist de homologação) por template de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str|dict>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. A ordem de listas semânticas (stories/parts/criteria/items)
é preservada; chaves de agrupamento (tipos de change) e chaves de dicts de atributos
são renderizadas em ordem estável, de modo que a MESMA spec produza SEMPRE o MESMO
output. O gerador NÃO inventa conteúdo de domínio — usa defaults/placeholders sensatos
quando a spec omite algo (o conteúdo de negócio é do agente). Só depende da stdlib →
importável/testável sem banco.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# ── Constantes de suporte ─────────────────────────────────────────────────────
_PLACEHOLDER = "_a definir_"
# Rótulos canônicos por tipo de change (release notes). Tipos fora do mapa caem
# no fallback de título-caso, sempre em ordem alfabética estável.
_CHANGE_TYPE_LABELS = {
    "added": "Adicionado",
    "breaking": "Mudanças Incompatíveis",
    "changed": "Alterado",
    "chore": "Manutenção",
    "deprecated": "Descontinuado",
    "docs": "Documentação",
    "feature": "Funcionalidades",
    "feat": "Funcionalidades",
    "fix": "Correções",
    "fixed": "Correções",
    "perf": "Performance",
    "removed": "Removido",
    "security": "Segurança",
}


# ── Helpers de renderização (determinísticos) ─────────────────────────────────
def _slug(text: str, fallback: str = "artifact") -> str:
    """Normaliza um texto num slug estável (minúsculo, ``[a-z0-9-]``, acentos dobrados)."""
    folded = unicodedata.normalize("NFKD", str(text))
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.strip().lower()).strip("-")
    return slug or fallback


def _label_of(item: Any, *keys: str) -> str:
    """Extrai um rótulo de um item que pode ser ``str`` ou ``dict``.

    Para ``dict``, tenta as ``keys`` na ordem dada; se nada casar, cai no primeiro
    valor de string encontrado por chave ordenada (determinístico)."""
    if isinstance(item, dict):
        for key in keys:
            val = item.get(key)
            if val:
                return str(val)
        for key in sorted(item):
            val = item.get(key)
            if isinstance(val, str) and val:
                return val
        return _PLACEHOLDER
    text = str(item).strip()
    return text or _PLACEHOLDER


def _checkbox_lines(items: list[Any], *keys: str) -> list[str]:
    """Renderiza itens como linhas de checklist ``- [ ] rótulo`` (ordem preservada)."""
    return [f"- [ ] {_label_of(it, *keys)}" for it in items]


# ── 1. Épico (markdown) ───────────────────────────────────────────────────────
def generate_epic(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec.get("title", "")).strip()
    if not title:
        return {"error": "missing_title"}

    goal = str(spec.get("goal", "")).strip() or _PLACEHOLDER
    stories = spec.get("stories") or []
    if not isinstance(stories, list):
        return {"error": "invalid_stories"}

    lines = [f"# Épico: {title}", "", "## Objetivo", goal, "", "## User Stories"]
    if stories:
        lines.extend(_checkbox_lines(stories, "story", "title", "name"))
    else:
        lines.append(f"- [ ] {_PLACEHOLDER}")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"epic-{_slug(title, 'epic')}.md",
        "kind": "epic",
    }


# ── 2. Breakdown de feature (markdown estruturado) ────────────────────────────
def generate_feature_breakdown(spec: dict[str, Any]) -> dict[str, Any]:
    feature = str(spec.get("feature", "")).strip()
    if not feature:
        return {"error": "missing_feature"}

    parts = spec.get("parts") or []
    if not isinstance(parts, list):
        return {"error": "invalid_parts"}

    lines = [f"# Breakdown da Feature: {feature}", ""]
    if not parts:
        lines += ["## Componentes", f"- {_PLACEHOLDER}"]
    else:
        for part in parts:
            name = _label_of(part, "name", "title")
            lines.append(f"## {name}")
            items = part.get("items") if isinstance(part, dict) else None
            if isinstance(items, list) and items:
                lines.extend(f"- {_label_of(it, 'name', 'title')}" for it in items)
            else:
                lines.append(f"- {_PLACEHOLDER}")
            lines.append("")

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": f"{_slug(feature, 'feature')}-breakdown.md",
        "kind": "feature_breakdown",
    }


# ── 3. Tasks de Jira (lista estruturada) ──────────────────────────────────────
def generate_jira_tasks(spec: dict[str, Any]) -> dict[str, Any]:
    breakdown = spec.get("breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        return {"error": "missing_breakdown"}

    project = str(spec.get("project", "TASK")).strip() or "TASK"
    tasks: list[dict[str, Any]] = []
    for idx, item in enumerate(breakdown, start=1):
        summary = _label_of(item, "summary", "name", "title")
        if isinstance(item, dict):
            issue_type = str(item.get("type") or "Task")
            description = str(item.get("description") or "")
        else:
            issue_type, description = "Task", ""
        tasks.append(
            {
                "key": f"{project}-{idx}",
                "summary": summary,
                "type": issue_type,
                "description": description,
            }
        )

    return {
        "artifact": {"tasks": tasks},
        "filename": f"{_slug(project, 'task')}-jira-tasks.json",
        "kind": "jira_tasks",
    }


# ── 4. Release notes (markdown) ───────────────────────────────────────────────
def generate_release_notes(spec: dict[str, Any]) -> dict[str, Any]:
    version = str(spec.get("version", "")).strip()
    if not version:
        return {"error": "missing_version"}

    changes = spec.get("changes") or []
    if not isinstance(changes, list):
        return {"error": "invalid_changes"}

    grouped: dict[str, list[str]] = {}
    for change in changes:
        if isinstance(change, dict):
            ctype = str(change.get("type") or "changed").strip().lower()
            desc = str(change.get("desc") or change.get("description") or "").strip()
        else:
            ctype, desc = "changed", str(change).strip()
        grouped.setdefault(ctype, []).append(desc or _PLACEHOLDER)

    lines = [f"# Release {version}", ""]
    if not grouped:
        lines += ["_Sem mudanças registradas._"]
    else:
        for ctype in sorted(grouped):
            label = _CHANGE_TYPE_LABELS.get(ctype, ctype.replace("_", " ").title())
            lines.append(f"## {label}")
            lines.extend(f"- {desc}" for desc in grouped[ctype])
            lines.append("")

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": f"release-{_slug(version, 'notes')}.md",
        "kind": "release_notes",
    }


# ── 5. User story (markdown "Como... quero... para...") ───────────────────────
def generate_user_stories(spec: dict[str, Any]) -> dict[str, Any]:
    role = str(spec.get("role", "")).strip()
    goal = str(spec.get("goal", "")).strip()
    if not role:
        return {"error": "missing_role"}
    if not goal:
        return {"error": "missing_goal"}

    benefit = str(spec.get("benefit", "")).strip() or _PLACEHOLDER
    criteria = spec.get("criteria") or []
    if not isinstance(criteria, list):
        return {"error": "invalid_criteria"}

    lines = [
        "## User Story",
        "",
        f"**Como** {role}, **quero** {goal}, **para** {benefit}.",
        "",
        "### Critérios de Aceite",
    ]
    if criteria:
        lines.extend(_checkbox_lines(criteria, "criterion", "text", "name"))
    else:
        lines.append(f"- [ ] {_PLACEHOLDER}")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"user-story-{_slug(role, 'story')}.md",
        "kind": "user_story",
    }


# ── 6. Checklist de homologação (markdown) ────────────────────────────────────
def generate_homologation_checklist(spec: dict[str, Any]) -> dict[str, Any]:
    items = spec.get("items")
    if not isinstance(items, list) or not items:
        return {"error": "missing_items"}

    title = str(spec.get("title", "")).strip() or "Homologação"
    lines = [f"# Checklist de {title}", ""]
    lines.extend(_checkbox_lines(items, "label", "name", "title"))

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"{_slug(title, 'homologation')}-checklist.md",
        "kind": "homologation_checklist",
    }
