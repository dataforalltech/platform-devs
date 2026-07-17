"""Geradores determinísticos de segurança (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``set_*``), estas tools NÃO tocam o
``SecurityStore``: são funções puras ``spec: dict -> dict`` que renderizam artefatos
de segurança (matriz de controles, spec de segurança de API, relatório de compliance
e handbook de segurança) por template de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str|dict>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. Chaves de dicionários de entrada e colunas derivadas
(assets/status) são renderizadas em ordem estável, de modo que a MESMA spec produza
SEMPRE o MESMO byte-a-byte. Só depende da stdlib → importável/testável sem banco.

O gerador FORMATA/scaffolda a spec fornecida: quando um conteúdo não vem na spec,
usa defaults/placeholders sensatos — NÃO inventa conteúdo de domínio (achados,
ameaças e controles vêm do agente).
"""

from __future__ import annotations

from typing import Any

# ── Constantes de suporte ─────────────────────────────────────────────────────
# Ordem canônica dos status de compliance (governa a ordenação estável do sumário).
_COMPLIANCE_STATUS_ORDER = ("pass", "partial", "fail", "na", "unknown")
# Status tratados como "aprovado" ao calcular o índice de conformidade.
_PASS_STATUSES = frozenset({"pass", "compliant", "ok"})
# Status excluídos do denominador do índice (não aplicável ao escopo).
_NA_STATUSES = frozenset({"na", "not_applicable", "n/a"})
# Baseline estrutural de controles de API (scaffolding — o agente refina/completa).
_API_BASELINE_CONTROLS = (
    "enforce_tls",
    "input_validation",
    "rate_limiting",
    "security_headers",
    "authz_checks",
    "audit_logging",
)


# ── Helpers de renderização (determinísticos) ─────────────────────────────────
def _yaml_scalar(value: Any) -> str:
    """Renderiza um escalar YAML. Bool/int/float saem crus; o resto é aspado."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"{}"'.format(str(value).replace("\\", "\\\\").replace('"', '\\"'))


def _yaml_block(data: dict[str, Any], indent: int) -> list[str]:
    """Serializa um dict plano como linhas ``chave: escalar`` (chaves ordenadas)."""
    pad = " " * indent
    return [f"{pad}{key}: {_yaml_scalar(data[key])}" for key in sorted(data)]


def _md_cell(value: Any) -> str:
    """Escapa um valor para uso seguro numa célula de tabela markdown."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _slug(text: str) -> str:
    """Converte um título num âncora/slug estável (a-z0-9 com hífens)."""
    out = "".join(c.lower() if c.isalnum() else "-" for c in str(text))
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def _asset_name(asset: Any) -> str:
    """Extrai o nome de um asset (string crua ou dict com ``name``)."""
    if isinstance(asset, dict):
        return str(asset.get("name", "")).strip()
    return str(asset).strip()


# ── 1. Matriz de controles de segurança ───────────────────────────────────────
def generate_security_controls(spec: dict[str, Any]) -> dict[str, Any]:
    """Gera uma matriz de controles (controles × assets) determinística por template.

    spec: ``{framework, assets?[], controls[]}``. Cada controle é
    ``{key|control_key, name?, category?, framework_ref?, applies_to?[]}``. Quando
    ``applies_to`` está ausente, o controle é marcado como cobrindo todos os assets.
    """
    framework = str(spec.get("framework", "")).strip()
    if not framework:
        return {"error": "missing_framework"}
    controls = spec.get("controls")
    if not isinstance(controls, list) or not controls:
        return {"error": "missing_controls"}

    assets: list[str] = []
    for raw in spec.get("assets") or []:
        name = _asset_name(raw)
        if name:
            assets.append(name)
    assets = sorted(set(assets))

    header = ["Control", "Name", "Category", "Framework", *assets]
    sep = ["---"] * len(header)
    lines: list[str] = [
        f"# Security Controls Matrix — {framework}",
        "",
        f"- Framework: {framework}",
        f"- Controls: {len(controls)}",
        f"- Assets: {len(assets)}",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]

    for ctrl in controls:
        if not isinstance(ctrl, dict):
            return {"error": "control_not_object", "control": ctrl}
        key = str(ctrl.get("key") or ctrl.get("control_key") or "").strip()
        if not key:
            return {"error": "control_missing_key", "control": ctrl}
        name = str(ctrl.get("name") or key).strip()
        category = str(ctrl.get("category") or "-").strip()
        fw_ref = str(ctrl.get("framework_ref") or framework).strip()
        applies = ctrl.get("applies_to")
        if isinstance(applies, list):
            covered = {_asset_name(a) for a in applies}
        else:
            covered = set(assets)  # sem applies_to explícito → cobre todos os assets
        cells = ["x" if asset in covered else "-" for asset in assets]
        row = [_md_cell(key), _md_cell(name), _md_cell(category), _md_cell(fw_ref), *cells]
        lines.append("| " + " | ".join(row) + " |")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "security-controls-matrix.md",
        "kind": "security_controls",
    }


# ── 2. Spec de segurança de API ────────────────────────────────────────────────
def generate_api_security_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Gera um spec de segurança de API (YAML) determinístico.

    spec: ``{endpoints[], auth?, threats?[], title?}``. Cada endpoint é
    ``{path, method?, auth_required?, scopes?[]}``. ``auth`` pode ser string
    (vira ``{type: <str>}``) ou dict; se ausente usa ``{type: bearer_jwt}``.
    """
    endpoints = spec.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        return {"error": "missing_endpoints"}

    title = str(spec.get("title") or "API Security Spec")
    auth = spec.get("auth")
    if isinstance(auth, dict):
        auth_map: dict[str, Any] = dict(auth)
    elif auth:
        auth_map = {"type": str(auth)}
    else:
        auth_map = {"type": "bearer_jwt"}

    lines: list[str] = [f"title: {_yaml_scalar(title)}", "auth:"]
    lines.extend(_yaml_block(auth_map, 2))

    lines.append("endpoints:")
    for ep in endpoints:
        if not isinstance(ep, dict):
            return {"error": "endpoint_not_object", "endpoint": ep}
        path = str(ep.get("path", "")).strip()
        if not path:
            return {"error": "endpoint_missing_path", "endpoint": ep}
        method = str(ep.get("method") or "GET").strip().upper()
        auth_required = bool(ep.get("auth_required", True))
        lines.append(f"  - path: {_yaml_scalar(path)}")
        lines.append(f"    method: {_yaml_scalar(method)}")
        lines.append(f"    auth_required: {_yaml_scalar(auth_required)}")
        scopes = ep.get("scopes") or []
        if scopes:
            lines.append("    scopes:")
            lines.extend(f"      - {_yaml_scalar(s)}" for s in scopes)

    threats = spec.get("threats") or []
    if threats:
        lines.append("threats:")
        for threat in threats:
            if isinstance(threat, dict):
                lines.append("  -")
                lines.extend(_yaml_block(threat, 4))
            else:
                lines.append(f"  - {_yaml_scalar(threat)}")

    lines.append("baseline_controls:")
    lines.extend(f"  - {_yaml_scalar(c)}" for c in _API_BASELINE_CONTROLS)

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "api-security-spec.yaml",
        "kind": "api_security_spec",
    }


# ── 3. Relatório de compliance ─────────────────────────────────────────────────
def generate_compliance_report(spec: dict[str, Any]) -> dict[str, Any]:
    """Gera um relatório de compliance (markdown) determinístico.

    spec: ``{standard, findings[{control, status, note?}], title?}``. Calcula o
    sumário por status (ordenado) e um índice de conformidade
    ``pass / (total − não-aplicáveis)``. Não inventa achados: apenas formata os
    fornecidos pelo agente.
    """
    standard = str(spec.get("standard", "")).strip()
    if not standard:
        return {"error": "missing_standard"}
    findings = spec.get("findings")
    if not isinstance(findings, list) or not findings:
        return {"error": "missing_findings"}

    title = str(spec.get("title") or f"{standard} Compliance Report")
    counts: dict[str, int] = {}
    rows: list[tuple[str, str, str]] = []
    passed = 0
    na = 0
    for finding in findings:
        if not isinstance(finding, dict):
            return {"error": "finding_not_object", "finding": finding}
        control = str(finding.get("control", "")).strip()
        if not control:
            return {"error": "finding_missing_control", "finding": finding}
        status = str(finding.get("status") or "unknown").strip().lower()
        note = str(finding.get("note") or "").strip()
        counts[status] = counts.get(status, 0) + 1
        if status in _PASS_STATUSES:
            passed += 1
        if status in _NA_STATUSES:
            na += 1
        rows.append((control, status, note))

    total = len(rows)
    assessed = total - na
    score = round(100.0 * passed / assessed, 1) if assessed else 0.0

    def _status_rank(status: str) -> tuple[int, str]:
        order = _COMPLIANCE_STATUS_ORDER
        return (order.index(status) if status in order else len(order), status)

    lines: list[str] = [
        f"# {title}",
        "",
        f"- Standard: {standard}",
        f"- Findings: {total}",
        f"- Compliance score: {score}%",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    for status in sorted(counts, key=_status_rank):
        lines.append(f"| {_md_cell(status)} | {counts[status]} |")

    lines.extend(["", "## Findings", "", "| Control | Status | Note |", "| --- | --- | --- |"])
    for control, status, note in rows:
        lines.append(f"| {_md_cell(control)} | {_md_cell(status)} | {_md_cell(note or '-')} |")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "compliance-report.md",
        "kind": "compliance_report",
    }


# ── 4. Handbook de segurança ───────────────────────────────────────────────────
def generate_security_handbook(spec: dict[str, Any]) -> dict[str, Any]:
    """Gera um handbook de segurança (markdown com TOC) determinístico.

    spec: ``{sections[{title, content?, items?[]}], title?}``. Cada seção vira uma
    entrada no índice e um bloco ``##``. Não inventa conteúdo: usa o que a seção
    fornece (ou um placeholder quando vazio).
    """
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        return {"error": "missing_sections"}

    title = str(spec.get("title") or "Security Handbook")
    toc: list[str] = ["## Table of Contents", ""]
    body: list[str] = []

    for idx, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            return {"error": "section_not_object", "section": section}
        sec_title = str(section.get("title") or f"Section {idx}").strip()
        anchor = _slug(sec_title)
        toc.append(f"{idx}. [{sec_title}](#{anchor})")

        body.extend(["", f"## {sec_title}", ""])
        content = str(section.get("content") or "").strip()
        items = section.get("items") or []
        if content:
            body.append(content)
        if items:
            if content:
                body.append("")
            body.extend(f"- {str(item).strip()}" for item in items)
        if not content and not items:
            body.append("_TODO: conteúdo desta seção._")

    lines = [f"# {title}", "", *toc, *body]
    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "security-handbook.md",
        "kind": "security_handbook",
    }
