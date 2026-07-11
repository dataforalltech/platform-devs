"""SuggestionStore + 4 tools de sugestão contra MySQL real (§16 / FID-02).

CRUD, filtros, histórico de status, validação de id, resolução de alias/deprecated via
EcosystemGraph (KB real) e ISOLAMENTO por tenant (banco-por-tenant). Store nunca mockado.
"""

from __future__ import annotations

import pytest

from src.db.store import SuggestionStoreError
from src.tools.suggestion_tool import (
    get_suggestion,
    list_suggestions,
    submit_suggestion,
    update_suggestion_status,
)

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── SuggestionStore puro ──────────────────────────────────────────────────────
async def test_store_create_persists_and_reads_back(stores_a):
    sug, _ = stores_a
    created = await sug.create(
        source_agent="test",
        target_repo="platform-x",
        category="bug",
        severity="medium",
        title="t",
        description="d",
    )
    assert created.target_repo == "platform-x"
    assert created.status == "pending"
    fetched = await sug.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.status_history[0].status == "pending"


async def test_store_id_format_is_sortable(stores_a):
    sug, _ = stores_a
    a = await sug.create(
        source_agent="a", target_repo="r", category="bug", severity="low", title="t1", description="d"
    )
    b = await sug.create(
        source_agent="a", target_repo="r", category="bug", severity="low", title="t2", description="d"
    )
    # A ordenação é garantida pelo prefixo de timestamp (até microssegundos).
    assert a.id.split("-")[0] <= b.id.split("-")[0]


async def test_store_get_returns_none_for_missing(stores_a):
    sug, _ = stores_a
    assert await sug.get("20260101T000000000000-aaaaaaaa") is None


async def test_store_validates_id_format(stores_a):
    sug, _ = stores_a
    with pytest.raises(SuggestionStoreError):
        await sug.get("invalid-id")
    with pytest.raises(SuggestionStoreError):
        await sug.get("20260101T000000-aaaaaaaa")  # formato antigo (sem microssegundos)
    with pytest.raises(SuggestionStoreError):
        await sug.get("20260101T000000000000-XYZ")  # hex inválido


async def test_store_list_returns_newest_first(stores_a):
    sug, _ = stores_a
    s1 = await sug.create(
        source_agent="a", target_repo="r", category="bug", severity="low", title="1", description="d"
    )
    s2 = await sug.create(
        source_agent="a", target_repo="r", category="bug", severity="low", title="2", description="d"
    )
    items = await sug.list()
    assert items[0].id == s2.id
    assert items[1].id == s1.id


async def test_store_list_filters_by_target_repo(stores_a):
    from src.models.suggestion import SuggestionFilters

    sug, _ = stores_a
    await sug.create(
        source_agent="a", target_repo="X", category="bug", severity="low", title="t", description="d"
    )
    await sug.create(
        source_agent="a", target_repo="Y", category="bug", severity="low", title="t", description="d"
    )
    res = await sug.list(SuggestionFilters(target_repo="X"))
    assert len(res) == 1
    assert res[0].target_repo == "X"


async def test_store_update_status_appends_history(stores_a):
    sug, _ = stores_a
    s = await sug.create(
        source_agent="a", target_repo="r", category="bug", severity="low", title="t", description="d"
    )
    assert len(s.status_history) == 1
    updated = await sug.update_status(s.id, "acknowledged", note="visto", by="caiog")
    assert updated.status == "acknowledged"
    assert len(updated.status_history) == 2
    assert updated.status_history[-1].note == "visto"
    # persistiu no DB
    reread = await sug.get(s.id)
    assert reread is not None
    assert reread.status == "acknowledged"
    assert len(reread.status_history) == 2


async def test_store_update_status_idempotent_when_no_change(stores_a):
    sug, _ = stores_a
    s = await sug.create(
        source_agent="a", target_repo="r", category="bug", severity="low", title="t", description="d"
    )
    updated = await sug.update_status(s.id, "pending")  # mesmo status, sem note
    assert len(updated.status_history) == 1  # sem nova entrada


async def test_store_update_status_unknown_id(stores_a):
    sug, _ = stores_a
    with pytest.raises(SuggestionStoreError):
        await sug.update_status("20260101T000000000000-aaaaaaaa", "accepted")


async def test_store_stats_summarizes(stores_a):
    sug, _ = stores_a
    await sug.create(
        source_agent="a", target_repo="X", category="bug", severity="high", title="t", description="d"
    )
    await sug.create(
        source_agent="a", target_repo="X", category="bug", severity="low", title="t", description="d"
    )
    await sug.create(
        source_agent="a", target_repo="Y", category="docs", severity="low", title="t", description="d"
    )
    s = await sug.stats()
    assert s["total"] == 3
    assert s["by_target"]["X"] == 2
    assert s["by_target"]["Y"] == 1
    assert s["by_severity"]["high"] == 1


# ── tools (com repo p/ o grafo + store tenant-scoped) ─────────────────────────
async def test_submit_suggestion_persists(repo, stores_a):
    sug, _ = stores_a
    res = await submit_suggestion(
        repo,
        sug,
        source_agent="claude",
        target_repo="platform-cdc",
        category="security",
        severity="high",
        title="Adicionar timeout no provider externo",
        description="Hoje a chamada não tem timeout configurado.",
        related_files=["app/services/provider.py"],
    )
    assert res["suggestion"]["target_repo"] == "platform-cdc"
    assert res["suggestion"]["category"] == "security"
    assert res["suggestion"]["status"] == "pending"
    assert res["suggestion"]["related_files"] == ["app/services/provider.py"]


async def test_submit_redirects_deprecated_target(repo, stores_a):
    """connectors-platform é deprecated; deve resolver para platform-connectors."""
    sug, _ = stores_a
    res = await submit_suggestion(
        repo,
        sug,
        source_agent="claude",
        target_repo="connectors-platform",
        category="docs",
        severity="low",
        title="Atualizar README",
        description="Apontar para o canônico no header.",
    )
    assert res["suggestion"]["target_repo"] == "connectors-platform"
    assert res["suggestion"]["target_repo_canonical"] == "platform-connectors"
    assert any("deprecado" in n.lower() for n in res["notes"])


async def test_submit_resolves_alias(repo, stores_a):
    """rag-service é alias de dataforall-rag-service."""
    sug, _ = stores_a
    res = await submit_suggestion(
        repo,
        sug,
        source_agent="claude",
        target_repo="rag-service",
        category="performance",
        severity="medium",
        title="Cache de embeddings",
        description="Reduziria latência em queries repetidas.",
    )
    assert res["suggestion"]["target_repo_canonical"] == "dataforall-rag-service"
    assert any("alias" in n.lower() for n in res["notes"])


async def test_submit_unknown_target_accepts_with_note(repo, stores_a):
    sug, _ = stores_a
    res = await submit_suggestion(
        repo,
        sug,
        source_agent="claude",
        target_repo="brand-new-service-xyz",
        category="improvement",
        severity="low",
        title="Algo",
        description="Detalhes.",
    )
    assert res["suggestion"]["target_repo_canonical"] is None
    assert any("não encontrado" in n.lower() for n in res["notes"])


async def test_submit_validates_category(repo, stores_a):
    sug, _ = stores_a
    with pytest.raises(ValueError, match="category"):
        await submit_suggestion(
            repo,
            sug,
            source_agent="a",
            target_repo="x",
            category="not-a-category",
            severity="low",
            title="t",
            description="d",
        )


async def test_submit_validates_severity(repo, stores_a):
    sug, _ = stores_a
    with pytest.raises(ValueError, match="severity"):
        await submit_suggestion(
            repo,
            sug,
            source_agent="a",
            target_repo="x",
            category="bug",
            severity="extreme",
            title="t",
            description="d",
        )


async def test_submit_rejects_overlong_title(repo, stores_a):
    sug, _ = stores_a
    with pytest.raises(ValueError, match="title"):
        await submit_suggestion(
            repo,
            sug,
            source_agent="a",
            target_repo="x",
            category="bug",
            severity="low",
            title="x" * 300,
            description="d",
        )


async def test_submit_rejects_empty_required_fields(repo, stores_a):
    sug, _ = stores_a
    with pytest.raises(ValueError):
        await submit_suggestion(
            repo,
            sug,
            source_agent="",
            target_repo="x",
            category="bug",
            severity="low",
            title="t",
            description="d",
        )
    with pytest.raises(ValueError):
        await submit_suggestion(
            repo,
            sug,
            source_agent="a",
            target_repo="",
            category="bug",
            severity="low",
            title="t",
            description="d",
        )


# ── list / get / update ───────────────────────────────────────────────────────
async def test_list_default_empty(repo, stores_a):
    sug, _ = stores_a
    res = await list_suggestions(repo, sug)
    assert res["total"] == 0
    assert res["suggestions"] == []


async def test_list_filters_by_target(repo, stores_a):
    sug, _ = stores_a
    await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="platform-cdc",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="platform-ml",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    res = await list_suggestions(repo, sug, target_repo="platform-cdc")
    assert res["total"] == 1
    assert res["suggestions"][0]["target_repo"] == "platform-cdc"


async def test_list_filters_by_status(repo, stores_a):
    sug, _ = stores_a
    r = await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="low",
        title="t2",
        description="d",
    )
    await update_suggestion_status(
        sug, suggestion_id=r["suggestion"]["id"], new_status="accepted", by="caiog"
    )
    res = await list_suggestions(repo, sug, status="accepted")
    assert res["total"] == 1
    assert res["suggestions"][0]["status"] == "accepted"


async def test_list_filters_by_severity(repo, stores_a):
    sug, _ = stores_a
    await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="critical",
        title="t",
        description="d",
    )
    await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    res = await list_suggestions(repo, sug, severity="critical")
    assert res["total"] == 1
    assert res["suggestions"][0]["severity"] == "critical"


async def test_list_resolves_alias_target_filter(repo, stores_a):
    sug, _ = stores_a
    await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="rag-service",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    res = await list_suggestions(repo, sug, target_repo="rag-service")
    assert res["total"] == 1


async def test_get_returns_full_payload(repo, stores_a):
    sug, _ = stores_a
    r = await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    res = await get_suggestion(sug, suggestion_id=r["suggestion"]["id"])
    assert res["found"] is True
    assert res["suggestion"]["title"] == "t"


async def test_get_returns_not_found(stores_a):
    sug, _ = stores_a
    res = await get_suggestion(sug, suggestion_id="20260101T000000000000-deadbeef")
    assert res["found"] is False


async def test_get_validates_id_format(stores_a):
    sug, _ = stores_a
    with pytest.raises(ValueError):
        await get_suggestion(sug, suggestion_id="bogus")


async def test_update_status_records_history(repo, stores_a):
    sug, _ = stores_a
    r = await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    sid = r["suggestion"]["id"]
    await update_suggestion_status(
        sug, suggestion_id=sid, new_status="acknowledged", note="visto", by="caiog"
    )
    await update_suggestion_status(
        sug, suggestion_id=sid, new_status="accepted", note="vai virar PR", by="caiog"
    )
    final = await get_suggestion(sug, suggestion_id=sid)
    assert final["suggestion"]["status"] == "accepted"
    assert len(final["suggestion"]["status_history"]) == 3
    notes = [h["note"] for h in final["suggestion"]["status_history"] if h["note"]]
    assert "vai virar PR" in notes


async def test_update_status_validates_status(repo, stores_a):
    sug, _ = stores_a
    r = await submit_suggestion(
        repo,
        sug,
        source_agent="a",
        target_repo="x",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    with pytest.raises(ValueError):
        await update_suggestion_status(sug, suggestion_id=r["suggestion"]["id"], new_status="invalid-status")


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(stores_a, stores_b):
    sug_a, _ = stores_a
    sug_b, _ = stores_b
    await sug_a.create(
        source_agent="a",
        target_repo="only-in-a",
        category="bug",
        severity="low",
        title="t",
        description="d",
    )
    assert len(await sug_a.list()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await sug_b.list() == []
