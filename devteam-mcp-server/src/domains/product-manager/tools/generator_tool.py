"""Geradores determinísticos do product-manager (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``), estas tools NÃO tocam o
``ProductManagerStore``: são funções puras ``spec: dict -> dict`` que renderizam
artefatos de produto (plano de release, critérios de aceite em Gherkin, score RICE
e documentos de handoff para arquitetura/design/engenharia) por template de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer valor dependente de tempo. Estes geradores FORMATAM/scaffoldam a spec
fornecida — quando algum conteúdo não vem na spec, usam placeholders sensatos, mas
NÃO inventam conteúdo de domínio (isso é do agente). A MESMA spec produz SEMPRE o
MESMO output. Só depende da stdlib → importável/testável sem banco.
"""

from __future__ import annotations

from typing import Any, cast

# ── Marcadores de placeholder (sem inventar conteúdo de domínio) ──────────────
_TBD = "_A definir._"


# ── Helpers de renderização (Markdown por string, determinísticos) ────────────
def _as_line(item: Any) -> str:
    """Renderiza um item de lista como texto. Dicts saem como ``chave: valor``
    com chaves ordenadas (determinismo, independente da ordem de inserção)."""
    if isinstance(item, dict):
        return ", ".join(f"{key}: {item[key]}" for key in sorted(item))
    return str(item)


def _md_bullets(items: list[Any]) -> list[str]:
    """Lista de bullets Markdown a partir de itens (ordem preservada). Vazio → TBD."""
    if not items:
        return [_TBD]
    return [f"- {_as_line(it)}" for it in items]


def _num(value: Any) -> float | None:
    """Coerção numérica estrita (aceita int/float e strings numéricas). None se falhar."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# ── 1. Plano de release (Markdown) ────────────────────────────────────────────
def generate_release_plan(spec: dict[str, Any]) -> dict[str, Any]:
    version = str(spec.get("version") or "").strip()
    if not version:
        return {"error": "missing_version"}

    scope = list(spec.get("scope") or [])
    milestones = list(spec.get("milestones") or [])

    lines: list[str] = [f"# Release Plan — v{version}", "", "## Scope", ""]
    lines.extend(_md_bullets(scope))
    lines.extend(["", "## Milestones", ""])

    if not milestones:
        lines.append(_TBD)
    else:
        for idx, ms in enumerate(milestones, start=1):
            if isinstance(ms, dict):
                name = str(ms.get("name") or f"Milestone {idx}").strip()
                date = str(ms.get("date") or "").strip()
                items = list(ms.get("items") or [])
            else:
                name, date, items = str(ms), "", []
            header = f"### {name}" + (f" — {date}" if date else "")
            lines.append(header)
            lines.extend(_md_bullets(items))
            lines.append("")
        lines.pop()  # remove a linha em branco final do laço

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": f"release-plan-v{version}.md",
        "kind": "release_plan",
    }


# ── 2. Critérios de aceite (Gherkin) ──────────────────────────────────────────
def generate_acceptance_criteria(spec: dict[str, Any]) -> dict[str, Any]:
    story = spec.get("story") or {}
    role = str(story.get("role") or "").strip()
    goal = str(story.get("goal") or "").strip()
    if not role or not goal:
        return {"error": "missing_story"}

    benefit = str(story.get("benefit") or "").strip()
    rules = list(spec.get("rules") or [])

    lines: list[str] = [f"Feature: {goal}", f"  As a {role}", f"  I want {goal}"]
    if benefit:
        lines.append(f"  So that {benefit}")
    lines.append("")

    if not rules:
        rules = [{}]  # um cenário-placeholder

    for idx, rule in enumerate(rules, start=1):
        if isinstance(rule, dict):
            title = str(rule.get("scenario") or rule.get("title") or f"Rule {idx}").strip()
            given = str(rule.get("given") or _TBD).strip()
            when = str(rule.get("when") or _TBD).strip()
            then = str(rule.get("then") or _TBD).strip()
        else:
            title = f"Rule {idx}"
            given, when = _TBD, _TBD
            then = str(rule).strip() or _TBD
        lines.append(f"  Scenario: {title}")
        lines.append(f"    Given {given}")
        lines.append(f"    When {when}")
        lines.append(f"    Then {then}")
        lines.append("")

    lines.pop()  # remove a linha em branco final
    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "acceptance-criteria.feature",
        "kind": "acceptance_criteria",
    }


# ── 3. Score RICE (cálculo determinístico) ────────────────────────────────────
def calculate_rice_score(spec: dict[str, Any]) -> dict[str, Any]:
    reach = _num(spec.get("reach"))
    impact = _num(spec.get("impact"))
    confidence = _num(spec.get("confidence"))
    effort = _num(spec.get("effort"))

    missing = [
        key
        for key, val in (
            ("reach", reach),
            ("impact", impact),
            ("confidence", confidence),
            ("effort", effort),
        )
        if val is None
    ]
    if missing:
        return {"error": "missing_factor", "missing": missing}
    # Type-narrowing p/ o mypy: os quatro são float aqui (missing == []).
    reach = cast(float, reach)
    impact = cast(float, impact)
    confidence = cast(float, confidence)
    effort = cast(float, effort)
    if effort <= 0:
        return {"error": "invalid_effort", "effort": effort}

    score = round(reach * impact * confidence / effort, 2)
    lines = [
        "# RICE Score",
        "",
        "| Factor | Value |",
        "| --- | --- |",
        f"| Reach | {reach:g} |",
        f"| Impact | {impact:g} |",
        f"| Confidence | {confidence:g} |",
        f"| Effort | {effort:g} |",
        f"| **RICE Score** | **{score:g}** |",
        "",
        "> RICE = (Reach × Impact × Confidence) / Effort",
    ]
    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "rice-score.md",
        "kind": "rice_score",
        "score": score,
    }


# ── 4-6. Documentos de handoff ────────────────────────────────────────────────
def _handoff_doc(
    feature: str, target: str, section: str, items: list[Any], kind: str, filename: str
) -> dict[str, Any]:
    """Renderiza um doc de handoff Markdown (cabeçalho + seção de itens + próximos passos)."""
    lines: list[str] = [
        f"# Handoff → {target}",
        "",
        f"**Feature:** {feature}",
        "",
        f"## {section}",
        "",
    ]
    lines.extend(_md_bullets(items))
    lines.extend(["", "## Handoff Checklist", "", "- [ ] Contexto revisado", "- [ ] Dúvidas alinhadas"])
    return {"artifact": "\n".join(lines) + "\n", "filename": filename, "kind": kind}


def generate_handoff_to_architecture(spec: dict[str, Any]) -> dict[str, Any]:
    feature = str(spec.get("feature") or "").strip()
    if not feature:
        return {"error": "missing_feature"}
    requirements = list(spec.get("requirements") or [])
    return _handoff_doc(
        feature,
        "Architecture",
        "Requirements",
        requirements,
        "handoff_architecture",
        "handoff-architecture.md",
    )


def generate_handoff_to_design(spec: dict[str, Any]) -> dict[str, Any]:
    feature = str(spec.get("feature") or "").strip()
    if not feature:
        return {"error": "missing_feature"}
    flows = list(spec.get("flows") or [])
    return _handoff_doc(feature, "Design", "Flows", flows, "handoff_design", "handoff-design.md")


def generate_handoff_to_engineering(spec: dict[str, Any]) -> dict[str, Any]:
    feature = str(spec.get("feature") or "").strip()
    if not feature:
        return {"error": "missing_feature"}
    specs = list(spec.get("specs") or [])
    return _handoff_doc(
        feature, "Engineering", "Specs", specs, "handoff_engineering", "handoff-engineering.md"
    )
