"""Testes das tools de política: layer, fallback, contract, forbidden."""

from __future__ import annotations

import pytest

from src.tools.policy_tool import (
    get_contract_change_policy,
    get_fallback_policy,
    get_forbidden_actions,
    get_layer_policy,
)


# --------------------------- Layer policy --------------------------- #
def test_layer_policy_returns_full_payload(repo):
    res = get_layer_policy(repo, layer="backend")
    assert res["layer"] == "backend"
    assert res["responsibilities"]
    assert res["can_do"]
    assert res["cannot_do"]
    assert res["wrong_examples"]
    assert res["correct_examples"]
    assert res["source"].endswith(".md")


def test_layer_policy_invalid(repo):
    with pytest.raises(ValueError):
        get_layer_policy(repo, layer="bogus")


# --------------------------- Forbidden actions --------------------------- #
def test_forbidden_actions_lists_all(repo):
    res = get_forbidden_actions(repo)
    assert res["total"] >= 14
    ids = {item["id"] for item in res["forbidden_actions"]}
    assert "silent-fallback" in ids
    assert "hardcoded-config" in ids
    assert "auth-bypass" in ids


def test_forbidden_actions_filtered_by_context(repo):
    res = get_forbidden_actions(repo, context="security")
    ids = {item["id"] for item in res["forbidden_actions"]}
    assert "auth-bypass" in ids


# --------------------------- Fallback policy --------------------------- #
def test_fallback_silent_is_blocked(repo):
    res = get_fallback_policy(repo, scenario="quero criar um fallback silencioso para a API X")
    assert res["fallback_allowed"] is False
    # rationale ou forbidden_cases devem citar silencioso/silenciosa
    blob = " ".join(res["forbidden_cases"]) + " " + res["rationale"]
    assert "silenc" in blob.lower()


def test_fallback_legitimate_path(repo):
    res = get_fallback_policy(
        repo,
        scenario="cache local quando provider de perfil de usuário está indisponível",
        service_name="user-profile",
    )
    assert res["fallback_allowed"] is True
    assert res["mandatory_conditions"]
    assert res["required_logs_metrics"]
    assert res["required_tests"]
    assert res["required_documentation"]


def test_fallback_requires_scenario(repo):
    with pytest.raises(ValueError):
        get_fallback_policy(repo, scenario="")


# --------------------------- Contract policy --------------------------- #
def test_contract_breaking_change_detected(repo):
    res = get_contract_change_policy(
        repo,
        provider_service="orders",
        consumer_services=["frontend", "billing"],
        contract_type="api",
        proposed_change="remover o campo customer_email do payload de /orders",
    )
    assert res["is_breaking_change"] is True
    assert res["risk_level"] in ("high", "critical")
    assert any("versionar" in r.lower() for r in res["compatibility_rules"])


def test_contract_additive_change(repo):
    res = get_contract_change_policy(
        repo,
        provider_service="orders",
        consumer_services=["frontend"],
        contract_type="api",
        proposed_change="adicionar campo opcional 'currency' ao payload de /orders",
    )
    assert res["is_breaking_change"] is False


def test_contract_without_consumers_is_high_risk(repo):
    res = get_contract_change_policy(
        repo,
        provider_service="orders",
        consumer_services=None,
        contract_type="api",
        proposed_change="adicionar campo opcional",
    )
    assert res["risk_level"] == "high"
    assert any("declarada" in i.lower() for i in res["expected_impacts"])


def test_contract_invalid_type(repo):
    with pytest.raises(ValueError):
        get_contract_change_policy(
            repo,
            provider_service="x",
            consumer_services=[],
            contract_type="bogus",
            proposed_change="x",
        )
