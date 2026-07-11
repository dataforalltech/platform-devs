"""Store canônico contra MySQL real (§16 / FID-02): CRUD de tokens, bcrypt real,
soft-delete (revogação), rotação, listagem e ISOLAMENTO por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

from src.db.store import TokenStoreError

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── register + validate (bcrypt real) ─────────────────────────────────────────
async def test_register_and_validate(store_a):
    record = await store_a.register(name="Alice", email="alice@test.com")
    assert record["token"]
    assert record["user_id"]
    validated = await store_a.validate(record["token"])
    assert validated is not None
    assert validated["name"] == "Alice"
    assert validated["email"] == "alice@test.com"
    assert validated["role"] == "developer"


async def test_invalid_token_returns_none(store_a):
    assert await store_a.validate("invalid-token-xyz") is None


async def test_register_never_stores_plaintext(store_a):
    record = await store_a.register(name="Sec", email="sec@test.com")
    validated = await store_a.validate(record["token"])
    # A coluna token guarda o hash bcrypt, nunca o plaintext.
    assert validated is not None
    assert validated["token"] != record["token"]
    assert validated["token"].startswith("$2")  # prefixo bcrypt


# ── revoke (soft-delete canônico) ─────────────────────────────────────────────
async def test_revoke_by_token(store_a):
    record = await store_a.register(name="Bob", email="bob@test.com")
    token = record["token"]
    result = await store_a.revoke(token)
    assert result["revoked"] is True
    assert await store_a.validate(token) is None


async def test_revoke_by_user_id(store_a):
    record = await store_a.register(name="Carol", email="carol@test.com")
    result = await store_a.revoke(record["user_id"])
    assert result["revoked"] is True
    assert result["affected"] == 1
    assert await store_a.validate(record["token"]) is None


async def test_revoke_missing_returns_false(store_a):
    result = await store_a.revoke("nonexistent")
    assert result["revoked"] is False
    assert result["affected"] == 0


# ── rotate ────────────────────────────────────────────────────────────────────
async def test_rotate_token(store_a):
    original = await store_a.register(name="Dave", email="dave@test.com")
    new = await store_a.rotate(original["user_id"])
    # Token antigo inválido (revogado)
    assert await store_a.validate(original["token"]) is None
    # Token novo válido, mesmo perfil
    assert await store_a.validate(new["token"]) is not None
    assert new["name"] == "Dave"
    assert new["token"] != original["token"]


async def test_rotate_missing_raises(store_a):
    with pytest.raises(TokenStoreError):
        await store_a.rotate("does-not-exist")


async def test_rotate_preserves_tenant_id(store_a):
    original = await store_a.register(name="K", email="k@test.com", tenant_id="tenant_xyz")
    rotated = await store_a.rotate(original["user_id"])
    validated = await store_a.validate(rotated["token"])
    assert validated is not None
    assert validated["tenant_id"] == "tenant_xyz"


# ── list_all (nunca expõe segredo) ────────────────────────────────────────────
async def test_list_all_excludes_revoked_by_default(store_a):
    await store_a.register(name="A", email="a@test.com")
    b = await store_a.register(name="B", email="b@test.com")
    await store_a.revoke(b["token"])
    records = await store_a.list_all()
    names = [r["name"] for r in records]
    assert "A" in names
    assert "B" not in names


async def test_list_all_include_revoked(store_a):
    a = await store_a.register(name="A", email="a@test.com")
    await store_a.revoke(a["token"])
    records = await store_a.list_all(include_revoked=True)
    revoked = [r for r in records if r["name"] == "A"]
    assert len(revoked) == 1
    assert revoked[0]["excluded"] == 1  # marcado como soft-deleted


async def test_list_all_hides_token_values(store_a):
    await store_a.register(name="E", email="e@test.com")
    records = await store_a.list_all()
    for r in records:
        assert "token" not in r
        assert "token_prefix" not in r


async def test_list_all_deserializes_scopes(store_a):
    await store_a.register(name="G", email="g@test.com", scopes=["deploy", "qa"])
    records = await store_a.list_all()
    match = next(r for r in records if r["name"] == "G")
    assert match["scopes"] == ["deploy", "qa"]


# ── touch ─────────────────────────────────────────────────────────────────────
async def test_touch_updates_last_used_at(store_a):
    record = await store_a.register(name="F", email="f@test.com")
    await store_a.touch(record["user_id"])
    validated = await store_a.validate(record["token"])
    assert validated is not None
    assert validated["last_used_at"] is not None


# ── atributos de negócio ──────────────────────────────────────────────────────
async def test_scopes_stored_and_returned(store_a):
    import json

    record = await store_a.register(name="Sc", email="sc@test.com", scopes=["deploy", "qa"])
    validated = await store_a.validate(record["token"])
    assert validated is not None
    # scopes é TEXT JSON no DB; validate devolve a linha crua (string JSON).
    assert json.loads(validated["scopes"]) == ["deploy", "qa"]


async def test_environment_stored_correctly(store_a):
    record = await store_a.register(name="H", email="h@test.com", environment="production")
    validated = await store_a.validate(record["token"])
    assert validated is not None
    assert validated["environment"] == "production"


async def test_tenant_id_defaults_to_none(store_a):
    record = await store_a.register(name="J", email="j@test.com")
    assert record["tenant_id"] is None
    validated = await store_a.validate(record["token"])
    assert validated is not None
    assert validated["tenant_id"] is None


async def test_expired_token_is_invalid(store_a):
    record = await store_a.register(name="Exp", email="exp@test.com", expires_in_days=-1)
    # expira no passado → validate ignora
    assert await store_a.validate(record["token"]) is None


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    reg = await store_a.register(name="OnlyInA", email="a@test.com")
    assert len(await store_a.list_all()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga tokens do A
    assert await store_b.list_all() == []
    assert await store_b.validate(reg["token"]) is None
