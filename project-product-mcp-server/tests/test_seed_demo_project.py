"""Valida que o seed do G9 produz payloads contract-validos (sem API viva)."""

from __future__ import annotations

import re

from scripts.seed_demo_project import (
    REPOS,
    _idempotency_key,
    build_binding_payload,
    build_product_payload,
    build_project_payload,
)

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def test_product_payload_is_contract_valid():
    payload = build_product_payload()
    assert payload["slug"] == "devteam-demo"
    assert payload["name"]
    assert _KEY_RE.match(payload["idempotency_key"])
    assert 8 <= len(payload["idempotency_key"]) <= 128


def test_project_payload_carries_product_id_and_valid_key():
    product_id = "11111111-1111-4111-8111-111111111111"
    payload = build_project_payload(product_id)
    assert payload["product_id"] == product_id
    assert payload["slug"] == "platform-devs"
    assert _KEY_RE.match(payload["idempotency_key"])


def test_binding_payloads_carry_external_link_and_safe_keys():
    assert REPOS, "o seed deve trazer ao menos um repositorio"
    for spec in REPOS:
        payload = build_binding_payload(spec)
        assert _KEY_RE.match(payload["idempotency_key"]), payload["idempotency_key"]
        assert payload["provider"] == "github"
        assert payload["external_link"]["owner"]
        assert payload["external_link"]["repo"]


def test_idempotency_key_sanitizes_forbidden_chars():
    key = _idempotency_key("binding-github:owner/repo name")
    assert "/" not in key and " " not in key
    assert _KEY_RE.match(key)
    assert len(key) >= 8
