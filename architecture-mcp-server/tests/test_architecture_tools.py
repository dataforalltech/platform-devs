"""Testes das tools do architecture-mcp-server.

Foco: a saída deve ser DERIVADA DOS INPUTS (nada de listas fixas/constantes).
Cada teste passa inputs custom e afirma que eles reaparecem na saída, e que
inputs *não* fornecidos não vazam valores canônicos antigos ('User'/'Admin').
"""

from __future__ import annotations

import re

from src.tools.architecture_tools import (
    generate_architecture,
    generate_c4_diagram,
    generate_solution_blueprint,
    status,
)


# ── generate_c4_diagram ─────────────────────────────────────────────────────── #
def test_c4_uses_custom_actors_not_fixed_list():
    result = generate_c4_diagram(
        system_name="Billing Platform",
        actors=[
            "Merchant",
            {"name": "Fraud Analyst", "type": "person", "description": "reviews cases"},
        ],
        containers=[{"name": "Payments API", "technology": "FastAPI"}, "Postgres"],
        relationships=[
            {
                "source": "Merchant",
                "target": "Payments API",
                "description": "submits charge",
            }
        ],
    )

    ctx = result["levels"]["system_context"]
    actor_names = {a["name"] for a in ctx["actors"]}
    # Inputs custom aparecem…
    assert "Merchant" in actor_names
    assert "Fraud Analyst" in actor_names
    # …e as constantes antigas do stub NÃO aparecem.
    assert "User" not in actor_names
    assert "Admin" not in actor_names

    assert result["system"]["name"] == "Billing Platform"
    assert result["system"]["id"] == "billing_platform"

    container_names = {c["name"] for c in result["levels"]["container"]["containers"]}
    assert container_names == {"Payments API", "Postgres"}
    # Metadados de tecnologia preservados a partir do dict de input.
    api = next(c for c in result["levels"]["container"]["containers"] if c["name"] == "Payments API")
    assert api["technology"] == "FastAPI"


def test_c4_actor_type_and_relationship_resolution():
    result = generate_c4_diagram(
        system_name="IoT Hub",
        actors=[{"name": "Weather Service", "type": "external_system"}],
        containers=["Ingestion Worker"],
        relationships=["Weather Service -> Ingestion Worker"],
    )
    actor = result["levels"]["system_context"]["actors"][0]
    assert actor["type"] == "external_system"

    rel = result["levels"]["system_context"]["relationships"][0]
    assert rel["source"] == "Weather Service"
    assert rel["target"] == "Ingestion Worker"
    # IDs resolvidos para os nós conhecidos (não slug arbitrário desconectado).
    assert rel["source_id"] == "weather_service"
    assert rel["target_id"] == "ingestion_worker"


def test_c4_empty_inputs_produce_empty_model_not_defaults():
    result = generate_c4_diagram(system_name="Empty")
    assert result["summary"] == {
        "actor_count": 0,
        "container_count": 0,
        "relationship_count": 0,
    }
    assert result["levels"]["system_context"]["actors"] == []
    assert result["levels"]["container"]["containers"] == []


def test_c4_deduplicates_repeated_actors():
    result = generate_c4_diagram(system_name="S", actors=["User", "User", {"name": "User"}])
    assert len(result["levels"]["system_context"]["actors"]) == 1


# ── generate_solution_blueprint ─────────────────────────────────────────────── #
def test_blueprint_components_derived_from_requirements():
    result = generate_solution_blueprint(
        solution_name="Loan Origination",
        requirements="Accept loan applications; score credit risk; notify applicants",
    )
    assert result["solution_name"] == "Loan Origination"
    # Cada requisito vira item + componente de negócio.
    assert result["input_requirements"] == [
        "Accept loan applications",
        "score credit risk",
        "notify applicants",
    ]
    biz_layer = next(ly for ly in result["layers"] if ly["name"] == "Business Logic")
    # Componentes derivam dos requisitos (slug), não de lista fixa.
    assert any("loan" in c or "credit" in c or "notify" in c for c in biz_layer["components"])
    assert "core_domain" not in biz_layer["components"]  # só quando não há requisitos


def test_blueprint_pattern_selection_is_traceable():
    result = generate_solution_blueprint(
        solution_name="Telemetry",
        requirements="Ingest millions of events from Kafka streams and scale horizontally",
    )
    names = {p["name"] for p in result["chosen_patterns"]}
    assert "Event-Driven Architecture" in names
    # A escolha é rastreável ao gatilho, não uma constante.
    edp = next(p for p in result["chosen_patterns"] if p["name"] == "Event-Driven Architecture")
    assert edp["triggered_by"]  # não vazio


def test_blueprint_nfrs_and_constraints_reflect_input():
    result = generate_solution_blueprint(
        solution_name="Health Records",
        requirements="Store patient data with encryption and full audit for compliance",
        constraints=["on-premises only", "LGPD"],
    )
    nfr_names = {n["name"] for n in result["non_functional_concerns"]}
    assert "Security" in nfr_names
    assert result["constraints"] == ["on-premises only", "LGPD"]


def test_blueprint_no_requirements_defaults_are_marked():
    result = generate_solution_blueprint(solution_name="Bare")
    assert result["input_requirements"] == []
    # Sem sinais → padrão default explicitamente marcado, não inventado.
    assert result["chosen_patterns"][0]["name"] == "Layered (N-Tier)"
    assert result["chosen_patterns"][0]["triggered_by"] == []


# ── generate_architecture ───────────────────────────────────────────────────── #
def test_architecture_style_derived_from_domain_and_constraints():
    result = generate_architecture(
        domain="real-time bidding ad exchange",
        constraints=["must scale to distributed regions", "decoupled teams"],
        quality_attributes=["scalability", "latency"],
    )
    assert result["domain"] == "real-time bidding ad exchange"
    # Estilo escolhido reflete os sinais de input.
    assert result["proposed_style"] in {"Microservices", "Event-Driven Microservices"}
    assert result["rationale"]["triggered_by"]
    # Táticas mapeiam cada atributo de qualidade fornecido.
    qas = {t["quality_attribute"] for t in result["tactics"]}
    assert qas == {"scalability", "latency"}
    assert all(t["heuristic_matched"] for t in result["tactics"])


def test_architecture_name_defaults_from_domain():
    result = generate_architecture(domain="inventory management")
    assert result["name"] == "inventory management architecture"


def test_architecture_no_signals_defaults_marked():
    result = generate_architecture(domain="", constraints=[], quality_attributes=[])
    assert result["proposed_style"] == "Modular Monolith"
    assert result["rationale"]["triggered_by"] == []
    assert result["tactics"] == []


# ── status ──────────────────────────────────────────────────────────────────── #
def test_status_reports_real_server_metadata():
    result = status()
    assert result["name"] == "architecture-mcp"
    assert result["status"] == "ok"
    assert result["tool_count"] == 4
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


# O contrato do servidor (schemas + campos de policy + PEP inner-token) agora é
# validado em test_mcp_server.py (sidecar mcp_http, Model C). O contrato FastMCP
# antigo (TOOL_REGISTRY/build_mcp/assert_schema_contract) foi aposentado.
