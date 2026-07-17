"""Unidade dos geradores determinísticos de arquitetura (COMPUTE PURO — sem DB, sem LLM).

Estes testes NÃO tocam o MySQL: os geradores são funções puras ``spec -> dict``.
Cada gerador tem ao menos uma fixture-spec com asserts em marcadores-chave do output,
mais um guard de spec inválida e um teste de DETERMINISMO (mesma spec 2x → idêntico)."""

from __future__ import annotations

import pytest

from src.tools.generator_tool import (
    generate_adr,
    generate_c4_diagram,
    generate_sequence_diagram,
)

# ── Fixtures de spec (reaproveitadas nos testes de conteúdo e de determinismo) ─
C4_SPEC = {
    "level": "container",
    "title": "Billing System — Containers",
    "elements": [
        {"name": "Customer", "type": "person", "description": "End user"},
        {"name": "API", "type": "container", "technology": "FastAPI", "description": "REST API"},
        {"name": "Ledger DB", "type": "database", "technology": "MySQL"},
    ],
    "relations": [
        {"from": "Customer", "to": "API", "text": "Uses", "technology": "HTTPS"},
        "API -> Ledger DB",
    ],
}
SEQUENCE_SPEC = {
    "title": "Checkout Flow",
    "participants": [{"name": "User", "alias": "u"}, "Gateway"],
    "messages": [
        {"from": "u", "to": "Gateway", "text": "POST /checkout"},
        {"from": "Gateway", "to": "u", "text": "201 Created", "type": "return"},
    ],
}
ADR_SPEC = {
    "number": 7,
    "title": "Adopt event sourcing for the ledger",
    "status": "Accepted",
    "context": "The ledger needs a full audit trail and temporal queries.",
    "decision": "Use event sourcing with an append-only event store.",
    "consequences": ["Full audit trail", "Higher read-model complexity"],
    "alternatives": ["CRUD with audit columns"],
}


# ── 1. Diagrama C4 (Mermaid) ──────────────────────────────────────────────────
def test_generate_c4_diagram_markers():
    out = generate_c4_diagram(C4_SPEC)
    art = out["artifact"]
    assert out["kind"] == "c4_diagram"
    assert out["filename"] == "c4-container.mmd"
    assert art.startswith("C4Container")
    assert "title Billing System — Containers" in art
    assert 'Person(customer, "Customer", "End user")' in art
    assert 'Container(api, "API", "FastAPI", "REST API")' in art
    assert 'ContainerDb(ledger_db, "Ledger DB", "MySQL", "")' in art
    # relação por dict (com tech) e por forma curta "A -> B" (ids resolvidos)
    assert 'Rel(customer, api, "Uses", "HTTPS")' in art
    assert 'Rel(api, ledger_db, "")' in art


@pytest.mark.parametrize("level", ["context", "container", "component"])
def test_generate_c4_diagram_levels(level):
    out = generate_c4_diagram({"level": level, "elements": ["Thing"]})
    header = {"context": "C4Context", "container": "C4Container", "component": "C4Component"}[level]
    assert out["artifact"].startswith(header)


def test_generate_c4_diagram_rejects_unsupported_level():
    out = generate_c4_diagram({"level": "deployment", "elements": ["x"]})
    assert out["error"] == "unsupported_level"


def test_generate_c4_diagram_requires_elements():
    assert generate_c4_diagram({"level": "context", "elements": []})["error"] == "missing_elements"


# ── 2. Diagrama de sequência (Mermaid) ────────────────────────────────────────
def test_generate_sequence_diagram_markers():
    out = generate_sequence_diagram(SEQUENCE_SPEC)
    art = out["artifact"]
    assert out["kind"] == "sequence_diagram"
    assert out["filename"] == "sequence.mmd"
    assert art.startswith("sequenceDiagram")
    assert "title Checkout Flow" in art
    assert "participant u as User" in art
    assert "participant Gateway" in art
    # seta síncrona default e seta de retorno (-->>)
    assert "u->>Gateway: POST /checkout" in art
    assert "Gateway-->>u: 201 Created" in art


def test_generate_sequence_diagram_declares_implicit_participants():
    # endpoints não declarados entram implicitamente (nada perdido)
    out = generate_sequence_diagram({"messages": [{"from": "A", "to": "B", "text": "ping"}]})
    art = out["artifact"]
    assert "participant A" in art and "participant B" in art
    assert "A->>B: ping" in art


def test_generate_sequence_diagram_requires_messages():
    assert generate_sequence_diagram({"participants": ["A"]})["error"] == "missing_messages"


# ── 3. ADR (Markdown) ─────────────────────────────────────────────────────────
def test_generate_adr_markers():
    out = generate_adr(ADR_SPEC)
    art = out["artifact"]
    assert out["kind"] == "adr"
    assert out["filename"] == "adr-0007-adopt_event_sourcing_for_the_ledger.md"
    assert art.startswith("# ADR 0007: Adopt event sourcing for the ledger")
    assert "## Status\n\nAccepted" in art
    assert "## Context" in art and "## Decision" in art and "## Consequences" in art
    # lista de consequências vira bullets
    assert "- Full audit trail" in art
    assert "## Alternatives Considered" in art
    assert "- CRUD with audit columns" in art


def test_generate_adr_defaults_status_and_placeholders():
    out = generate_adr({"title": "Minimal decision"})
    art = out["artifact"]
    assert out["filename"] == "adr-minimal_decision.md"
    assert art.startswith("# ADR: Minimal decision")
    assert "## Status\n\nProposed" in art
    # blocos sem conteúdo caem para placeholder, não somem
    assert "## Context\n\nTBD" in art


def test_generate_adr_requires_title():
    assert generate_adr({"context": "x"})["error"] == "missing_title"


# ── Determinismo global (mesma spec chamada 2x → output idêntico) ─────────────
@pytest.mark.parametrize(
    "fn,spec",
    [
        (generate_c4_diagram, C4_SPEC),
        (generate_c4_diagram, {"level": "context", "elements": ["A", "B"], "relations": ["A -> B"]}),
        (generate_sequence_diagram, SEQUENCE_SPEC),
        (generate_adr, ADR_SPEC),
    ],
)
def test_generators_are_deterministic(fn, spec):
    assert fn(dict(spec)) == fn(dict(spec))
