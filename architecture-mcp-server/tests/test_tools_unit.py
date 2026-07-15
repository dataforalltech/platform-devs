"""Unidade das tools que NÃO tocam o banco: os *builders* determinísticos preservados
(modelo C4, proposta de arquitetura, blueprint de solução) e o guard de validação do
artefato que retorna antes do store."""

from __future__ import annotations

from src.tools.architecture_blueprint_tool import build_architecture_proposal
from src.tools.artifact_tool import save_artifact
from src.tools.c4_diagram_tool import build_c4_model
from src.tools.solution_blueprint_tool import build_solution_blueprint


# ── build_c4_model (100% derivado dos inputs, nada inventado) ─────────────────
def test_build_c4_model_is_deterministic():
    model = build_c4_model(
        system_name="Billing",
        actors=["Customer", {"name": "Ledger", "type": "external_system"}],
        containers=[{"name": "API", "technology": "FastAPI"}],
        relationships=["Customer -> API", {"source": "API", "target": "Ledger"}],
    )
    assert model["system"] == {"id": "billing", "name": "Billing"}
    assert model["summary"] == {"actor_count": 2, "container_count": 1, "relationship_count": 2}
    ctx = model["levels"]["system_context"]
    assert {a["name"] for a in ctx["actors"]} == {"Customer", "Ledger"}
    # empty relationship string ignorada, nada inventado
    empty = build_c4_model(system_name="")
    assert empty["system"]["name"] == "System"
    assert empty["summary"]["relationship_count"] == 0


def test_build_c4_model_dedupes_actors_and_containers():
    model = build_c4_model(system_name="S", actors=["X", "X", ""], containers=["C", "C"])
    assert model["summary"]["actor_count"] == 1
    assert model["summary"]["container_count"] == 1


# ── build_architecture_proposal (heurística de palavra-chave rastreável) ──────
def test_build_architecture_proposal_style_from_keywords():
    proposal = build_architecture_proposal(
        domain="IoT telemetry stream",
        constraints=["kafka"],
        quality_attributes=["scalability", "security"],
    )
    assert proposal["proposed_style"] == "Event-Driven Microservices"
    assert proposal["rationale"]["triggered_by"]  # rastreável
    tactic_map = {t["quality_attribute"]: t["heuristic_matched"] for t in proposal["tactics"]}
    assert tactic_map["scalability"] is True and tactic_map["security"] is True


def test_build_architecture_proposal_defaults_without_signal():
    proposal = build_architecture_proposal(domain="", quality_attributes=["unknown-qa"])
    assert proposal["proposed_style"] == "Modular Monolith"
    assert proposal["rationale"]["triggered_by"] == []
    assert proposal["tactics"][0]["heuristic_matched"] is False


# ── build_solution_blueprint (camadas/padrões/NFRs derivados) ─────────────────
def test_build_solution_blueprint_derives_layers_and_patterns():
    bp = build_solution_blueprint(
        requirements="cache de leitura; multi-tenant SaaS",
        solution_name="Portal",
        context="latência baixa",
    )
    assert bp["solution_name"] == "Portal"
    assert len(bp["input_requirements"]) == 2
    pattern_names = {p["name"] for p in bp["chosen_patterns"]}
    assert "Caching Layer" in pattern_names or "Multi-Tenancy" in pattern_names
    layer_names = [layer["name"] for layer in bp["layers"]]
    assert layer_names == ["Presentation", "Application / API", "Business Logic", "Data"]


def test_build_solution_blueprint_default_pattern_without_signal():
    bp = build_solution_blueprint(requirements="", solution_name="Empty")
    assert bp["chosen_patterns"][0]["name"] == "Layered (N-Tier)"
    assert bp["input_requirements"] == []


# ── guard de validação do artefato (retorna antes do store) ───────────────────
async def test_save_artifact_rejects_invalid_kind_before_store():
    out = await save_artifact(None, kind="nope", target="t", content="c")  # type: ignore[arg-type]
    assert out["error"] == "invalid_kind"
