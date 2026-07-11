"""ConfigStore canônico contra MySQL real (§16 / FID-02): CRUD encriptado, upsert de
chave natural (namespace, config_key), soft-delete, agregações e ISOLAMENTO por tenant
(banco-por-tenant)."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── CRUD encriptado ────────────────────────────────────────────────────────────
async def test_set_get_roundtrip_is_encrypted(store_a):
    await store_a.set("credentials.acr", "ACR_PASSWORD", "s3cr3t")
    assert await store_a.get("credentials.acr", "ACR_PASSWORD") == "s3cr3t"


async def test_get_absent_returns_none(store_a):
    assert await store_a.get("credentials.acr", "MISSING") is None
    assert await store_a.get("nao.existe", "X") is None


async def test_set_upserts_natural_key(store_a):
    await store_a.set("env.dev", "DATABASE_URL", "v1")
    await store_a.set("env.dev", "DATABASE_URL", "v2")  # ON DUPLICATE KEY: não duplica
    assert await store_a.get("env.dev", "DATABASE_URL") == "v2"
    keys = await store_a.list_keys("env.dev")
    assert keys["env.dev"] == ["DATABASE_URL"]  # uma única linha


async def test_ciphertext_never_plaintext(store_a):
    # O valor no banco é a CIFRA Fernet, nunca o texto claro (defense-in-depth).
    await store_a.set("credentials.github", "GITHUB_TOKEN", "ghp_plain")
    res = await store_a._repo.find(where={"namespace": "credentials.github", "config_key": "GITHUB_TOKEN"})
    stored = res.rows()[0]["value_encrypted"]
    assert stored != "ghp_plain"
    assert "ghp_plain" not in stored


# ── Leitura em lote ────────────────────────────────────────────────────────────
async def test_get_namespace_decrypts_all(store_a):
    await store_a.set("env.prod", "A", "1")
    await store_a.set("env.prod", "B", "2")
    assert await store_a.get_namespace("env.prod") == {"A": "1", "B": "2"}


async def test_get_namespace_empty(store_a):
    assert await store_a.get_namespace("env.void") == {}


async def test_list_keys_all_and_scoped(store_a):
    await store_a.set("credentials.acr", "ACR_USERNAME", "u")
    await store_a.set("credentials.github", "GITHUB_TOKEN", "t")
    await store_a.set("workspace", "REPOS_ROOT", "/repos")

    all_keys = await store_a.list_keys()
    assert all_keys == {
        "credentials.acr": ["ACR_USERNAME"],
        "credentials.github": ["GITHUB_TOKEN"],
        "workspace": ["REPOS_ROOT"],
    }
    assert await store_a.list_keys("credentials.acr") == {"credentials.acr": ["ACR_USERNAME"]}


async def test_list_namespaces_and_exists(store_a):
    await store_a.set("env.dev", "X", "1")
    await store_a.set("tenants.acme", "Y", "2")
    assert await store_a.list_namespaces() == ["env.dev", "tenants.acme"]
    assert await store_a.namespace_exists("env.dev") is True
    assert await store_a.namespace_exists("env.nope") is False


# ── Soft-delete ────────────────────────────────────────────────────────────────
async def test_delete_key_soft_delete(store_a):
    await store_a.set("credentials.acr", "ACR_PASSWORD", "p")
    assert await store_a.delete("credentials.acr", "ACR_PASSWORD") is True
    assert await store_a.get("credentials.acr", "ACR_PASSWORD") is None
    # deletar de novo: nada vivo para deletar
    assert await store_a.delete("credentials.acr", "ACR_PASSWORD") is False


async def test_delete_reactivates_on_reset(store_a):
    # re-set após soft-delete reativa a linha via upsert (mesma chave única).
    await store_a.set("env.dev", "K", "old")
    await store_a.delete("env.dev", "K")
    await store_a.set("env.dev", "K", "new")
    assert await store_a.get("env.dev", "K") == "new"
    assert (await store_a.list_keys("env.dev"))["env.dev"] == ["K"]


async def test_delete_namespace(store_a):
    await store_a.set("env.stage", "A", "1")
    await store_a.set("env.stage", "B", "2")
    assert await store_a.delete_namespace("env.stage") is True
    assert await store_a.get_namespace("env.stage") == {}
    assert await store_a.delete_namespace("env.stage") is False


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.set("credentials.acr", "ONLY_IN_A", "x")
    assert await store_a.get("credentials.acr", "ONLY_IN_A") == "x"
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.get("credentials.acr", "ONLY_IN_A") is None
    assert await store_b.list_namespaces() == []
