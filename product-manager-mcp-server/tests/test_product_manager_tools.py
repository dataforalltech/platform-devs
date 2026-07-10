"""Testes das tools do product-manager-mcp-server.

Cobre cada função de src/tools/product_manager_tools.py com inputs variados.
generate_feature_spec DERIVA a saída dos inputs (feature/objective) — os testes
afirmam que os inputs reaparecem e que o default é marcado explicitamente. As
demais tools são catálogos fixos: validamos o contrato (chaves + tipos) que o
dispatcher e o gateway consomem.
"""

from __future__ import annotations

from src.tools.product_manager_tools import (
    define_product_vision,
    generate_feature_spec,
    generate_go_to_market_brief,
    generate_release_plan,
    stub_tool,
)


# ── generate_feature_spec — saída derivada dos inputs ────────────────────────── #
def test_feature_spec_uses_custom_feature_and_objective():
    result = generate_feature_spec(
        feature="Dark Mode", objective="Reduce eye strain at night"
    )
    assert result["title"] == "Feature Spec: Dark Mode"
    assert result["feature"] == "Dark Mode"
    # objective fornecido é preservado (não sobrescrito pelo default derivado).
    assert result["objective"] == "Reduce eye strain at night"
    assert result["status"] == "draft"
    # contrato estrutural consumido a jusante.
    assert isinstance(result["user_stories"], list) and result["user_stories"]
    assert isinstance(result["acceptance_criteria"], list) and result["acceptance_criteria"]


def test_feature_spec_objective_defaults_from_feature():
    # Sem objective → default é DERIVADO do nome da feature, não uma constante fixa.
    result = generate_feature_spec(feature="CSV Export")
    assert result["title"] == "Feature Spec: CSV Export"
    assert result["feature"] == "CSV Export"
    assert result["objective"] == "Implement CSV Export"


def test_feature_spec_empty_objective_string_falls_back():
    # objective="" é falsy → cai no default derivado (cobre o ramo `or`).
    result = generate_feature_spec(feature="Search", objective="")
    assert result["objective"] == "Implement Search"


def test_feature_spec_all_defaults():
    result = generate_feature_spec()
    assert result["feature"] == "Feature"
    assert result["title"] == "Feature Spec: Feature"
    assert result["objective"] == "Implement Feature"


# ── generate_go_to_market_brief — catálogo fixo, contrato estável ────────────── #
def test_gtm_brief_contract():
    result = generate_go_to_market_brief()
    assert result["title"] == "Go-to-Market Brief"
    assert result["status"] == "draft"
    for key in ("target_segment", "key_messages", "channels", "success_metrics"):
        assert isinstance(result[key], list) and result[key]
    assert isinstance(result["launch_timing"], str)


# ── define_product_vision ────────────────────────────────────────────────────── #
def test_product_vision_contract():
    result = define_product_vision()
    assert result["title"] == "Product Vision"
    assert result["status"] == "active"
    assert isinstance(result["vision"], str) and result["vision"]
    assert isinstance(result["mission"], str) and result["mission"]
    assert isinstance(result["goals"], list) and len(result["goals"]) == 3


# ── generate_release_plan ────────────────────────────────────────────────────── #
def test_release_plan_contract():
    result = generate_release_plan()
    assert result["title"] == "Release Plan"
    assert result["status"] == "planned"
    assert result["phases"] == ["Alpha", "Beta", "GA"]
    # timeline e features_per_phase cobrem cada fase declarada.
    assert set(result["timeline"]) == {"alpha", "beta", "ga"}
    assert set(result["features_per_phase"]) == {"alpha", "beta", "ga"}
    assert all(isinstance(v, int) for v in result["features_per_phase"].values())


# ── stub_tool (status) ───────────────────────────────────────────────────────── #
def test_stub_tool_returns_ok():
    assert stub_tool() == {"status": "ok"}
