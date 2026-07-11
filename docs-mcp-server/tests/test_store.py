"""Store canônico contra MySQL real (§16 / FID-02): CRUD de auditoria, upsert de
índice por chave natural, e ISOLAMENTO por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Audits ─────────────────────────────────────────────────────────────────────
async def test_save_audit_returns_id_and_shape(store_a):
    audit_id = await store_a.save_audit(
        repo_path="/repo",
        score=88,
        grade="B",
        summary={"total_docs": 3},
        details={"x": 1},
        duration_ms=12,
    )
    assert isinstance(audit_id, int) and audit_id > 0

    audits = await store_a.list_audits(repo_path="/repo")
    assert len(audits) == 1
    row = audits[0]
    assert row["id"] == audit_id
    assert row["score"] == 88
    assert row["grade"] == "B"
    assert row["title"] == "Audit: B"
    assert row["summary"] == {"total_docs": 3}  # JSON parseado de volta p/ dict
    assert row["details"] == {"x": 1}


async def test_list_audits_filters_by_repo(store_a):
    await store_a.save_audit("/a", 50, "D", {}, {})
    await store_a.save_audit("/b", 90, "A", {}, {})

    assert len(await store_a.list_audits()) == 2
    assert {r["repo_path"] for r in await store_a.list_audits(repo_path="/a")} == {"/a"}
    assert len(await store_a.list_audits(repo_path="/a")) == 1


async def test_list_audits_newest_first_and_limit(store_a):
    first = await store_a.save_audit("/r", 50, "D", {}, {})
    second = await store_a.save_audit("/r", 80, "B", {}, {})

    audits = await store_a.list_audits(repo_path="/r")
    assert [a["id"] for a in audits] == [second, first]  # mais recente primeiro
    assert len(await store_a.list_audits(repo_path="/r", limit=1)) == 1


# ── Document index (upsert por chave natural) ──────────────────────────────────
async def test_upsert_doc_index_inserts_then_updates(store_a):
    await store_a.upsert_doc_index(
        repo_path="/repo",
        file_path="README.md",
        doc_type="readme",
        title="My Service",
        word_count=120,
        last_modified="2026-01-01T00:00:00+00:00",
        content_hash="abc123",
    )
    indexed = await store_a.get_index("/repo")
    assert len(indexed) == 1
    assert indexed[0]["title"] == "My Service"  # doc_title promovido a coluna
    assert indexed[0]["file_path"] == "README.md"
    assert indexed[0]["word_count"] == 120

    # Re-scan do mesmo (repo_path, file_path) → ON DUPLICATE KEY: não duplica, atualiza.
    await store_a.upsert_doc_index(
        repo_path="/repo",
        file_path="README.md",
        doc_type="readme",
        title="My Service Renamed",
        word_count=200,
        last_modified="2026-02-02T00:00:00+00:00",
        content_hash="def456",
    )
    indexed = await store_a.get_index("/repo")
    assert len(indexed) == 1  # sem duplicata
    assert indexed[0]["title"] == "My Service Renamed"
    assert indexed[0]["word_count"] == 200


async def test_get_index_sorted_by_file_path(store_a):
    await store_a.upsert_doc_index("/repo", "z.md", "other", "Z", 1, None, None)
    await store_a.upsert_doc_index("/repo", "a.md", "other", "A", 1, None, None)
    files = [r["file_path"] for r in await store_a.get_index("/repo")]
    assert files == ["a.md", "z.md"]


async def test_search_index_matches_file_path(store_a):
    await store_a.upsert_doc_index("/repo", "docs/guide.md", "other", "Guide", 5, None, None)
    await store_a.upsert_doc_index("/repo", "README.md", "readme", "Home", 5, None, None)

    hits = await store_a.search_index("/repo", "guide")
    assert len(hits) == 1
    assert hits[0]["file_path"] == "docs/guide.md"
    assert hits[0]["title"] == "Guide"

    assert await store_a.search_index("/repo", "nope") == []


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_audit("/only-in-a", 70, "C", {}, {})
    await store_a.upsert_doc_index("/only-in-a", "README.md", "readme", "A", 1, None, None)

    assert len(await store_a.list_audits()) == 1
    assert len(await store_a.get_index("/only-in-a")) == 1

    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_audits() == []
    assert await store_b.get_index("/only-in-a") == []
