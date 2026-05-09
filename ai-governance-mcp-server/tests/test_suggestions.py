"""Testes do SuggestionStore + 4 tools de sugestão.

Usa repo isolado por test (com suggestions_path em tmp_path) para não poluir
o store real e não interferir com outros testes que rodam em paralelo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.knowledge.governance_repository import GovernanceRepository
from src.knowledge.suggestion_store import SuggestionStore, SuggestionStoreError
from src.tools.suggestion_tool import (
    SuggestionsUnavailable,
    get_suggestion,
    list_suggestions,
    submit_suggestion,
    update_suggestion_status,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_PATH = PROJECT_ROOT / "knowledge-base"


@pytest.fixture
def isolated_repo(tmp_path) -> GovernanceRepository:
    """Repo carregando KB real mas com suggestions_path isolado em tmp_path."""
    return GovernanceRepository(
        kb_path=KB_PATH,
        suggestions_path=tmp_path / "suggestions",
    )


# --------------------------- SuggestionStore puro --------------------------- #
def test_store_creates_directory_if_missing(tmp_path):
    target = tmp_path / "deep" / "subdir"
    assert not target.exists()
    SuggestionStore(target)
    assert target.exists()


def test_store_create_persists_json(tmp_path):
    store = SuggestionStore(tmp_path)
    s = store.create(
        source_agent="test",
        target_repo="platform-x",
        category="bug",
        severity="medium",
        title="t",
        description="d",
    )
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert files[0].stem == s.id
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["target_repo"] == "platform-x"
    assert payload["status"] == "pending"


def test_store_id_format_is_sortable(tmp_path):
    store = SuggestionStore(tmp_path)
    a = store.create(
        source_agent="a", target_repo="r", category="bug", severity="low",
        title="t1", description="d",
    )
    # ID tem prefixo timestamp; segundo create gera timestamp >= primeiro.
    b = store.create(
        source_agent="a", target_repo="r", category="bug", severity="low",
        title="t2", description="d",
    )
    assert a.id <= b.id


def test_store_get_returns_none_for_missing(tmp_path):
    store = SuggestionStore(tmp_path)
    # ID válido em formato mas não existente
    valid_missing = "20260101T000000000000-aaaaaaaa"
    assert store.get(valid_missing) is None


def test_store_validates_id_format(tmp_path):
    store = SuggestionStore(tmp_path)
    with pytest.raises(SuggestionStoreError):
        store.get("invalid-id")
    with pytest.raises(SuggestionStoreError):
        store.get("20260101T000000-aaaaaaaa")  # formato antigo (sem microssegundos)
    with pytest.raises(SuggestionStoreError):
        store.get("20260101T000000000000-XYZ")  # hex inválido


def test_store_list_returns_newest_first(tmp_path):
    store = SuggestionStore(tmp_path)
    s1 = store.create(source_agent="a", target_repo="r", category="bug", severity="low", title="primeira", description="d")
    s2 = store.create(source_agent="a", target_repo="r", category="bug", severity="low", title="segunda", description="d")
    items = store.list()
    # Mais novos primeiro
    assert items[0].id == s2.id
    assert items[1].id == s1.id


def test_store_list_filters_by_target_repo(tmp_path):
    from src.models.suggestion import SuggestionFilters
    store = SuggestionStore(tmp_path)
    store.create(source_agent="a", target_repo="X", category="bug", severity="low", title="t", description="d")
    store.create(source_agent="a", target_repo="Y", category="bug", severity="low", title="t", description="d")
    res = store.list(SuggestionFilters(target_repo="X"))
    assert len(res) == 1
    assert res[0].target_repo == "X"


def test_store_update_status_appends_history(tmp_path):
    store = SuggestionStore(tmp_path)
    s = store.create(source_agent="a", target_repo="r", category="bug", severity="low", title="t", description="d")
    assert len(s.status_history) == 1
    assert s.status_history[0].status == "pending"
    updated = store.update_status(s.id, "acknowledged", note="visto", by="caiog")
    assert updated.status == "acknowledged"
    assert len(updated.status_history) == 2
    assert updated.status_history[-1].note == "visto"


def test_store_update_status_idempotent_when_no_change(tmp_path):
    store = SuggestionStore(tmp_path)
    s = store.create(source_agent="a", target_repo="r", category="bug", severity="low", title="t", description="d")
    updated = store.update_status(s.id, "pending")  # mesmo status, sem note
    assert len(updated.status_history) == 1  # sem nova entrada


def test_store_update_status_unknown_id(tmp_path):
    store = SuggestionStore(tmp_path)
    with pytest.raises(SuggestionStoreError):
        store.update_status("20260101T000000000000-aaaaaaaa", "accepted")


def test_store_stats_summarizes(tmp_path):
    store = SuggestionStore(tmp_path)
    store.create(source_agent="a", target_repo="X", category="bug", severity="high", title="t", description="d")
    store.create(source_agent="a", target_repo="X", category="bug", severity="low", title="t", description="d")
    store.create(source_agent="a", target_repo="Y", category="docs", severity="low", title="t", description="d")
    s = store.stats()
    assert s["total"] == 3
    assert s["by_target"]["X"] == 2
    assert s["by_target"]["Y"] == 1
    assert s["by_severity"]["high"] == 1


# --------------------------- tools com fixture isolada --------------------------- #
def test_submit_suggestion_persists(isolated_repo):
    res = submit_suggestion(
        isolated_repo,
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


def test_submit_redirects_deprecated_target(isolated_repo):
    """connectors-platform é deprecated; deve resolver para platform-connectors."""
    res = submit_suggestion(
        isolated_repo,
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


def test_submit_resolves_alias(isolated_repo):
    """rag-service é alias de dataforall-rag-service."""
    res = submit_suggestion(
        isolated_repo,
        source_agent="claude",
        target_repo="rag-service",
        category="performance",
        severity="medium",
        title="Cache de embeddings",
        description="Reduziria latência em queries repetidas.",
    )
    assert res["suggestion"]["target_repo_canonical"] == "dataforall-rag-service"
    assert any("alias" in n.lower() for n in res["notes"])


def test_submit_unknown_target_accepts_with_note(isolated_repo):
    """Target desconhecido é aceito mas marcado com nota — não bloqueamos."""
    res = submit_suggestion(
        isolated_repo,
        source_agent="claude",
        target_repo="brand-new-service-xyz",
        category="improvement",
        severity="low",
        title="Algo",
        description="Detalhes.",
    )
    assert res["suggestion"]["target_repo_canonical"] is None
    assert any("não encontrado" in n.lower() for n in res["notes"])


def test_submit_validates_category(isolated_repo):
    with pytest.raises(ValueError, match="category"):
        submit_suggestion(
            isolated_repo, source_agent="a", target_repo="x",
            category="not-a-category", severity="low", title="t", description="d",
        )


def test_submit_validates_severity(isolated_repo):
    with pytest.raises(ValueError, match="severity"):
        submit_suggestion(
            isolated_repo, source_agent="a", target_repo="x",
            category="bug", severity="extreme", title="t", description="d",
        )


def test_submit_rejects_overlong_title(isolated_repo):
    long_title = "x" * 300
    with pytest.raises(ValueError, match="title"):
        submit_suggestion(
            isolated_repo, source_agent="a", target_repo="x",
            category="bug", severity="low", title=long_title, description="d",
        )


def test_submit_rejects_empty_required_fields(isolated_repo):
    with pytest.raises(ValueError):
        submit_suggestion(
            isolated_repo, source_agent="", target_repo="x",
            category="bug", severity="low", title="t", description="d",
        )
    with pytest.raises(ValueError):
        submit_suggestion(
            isolated_repo, source_agent="a", target_repo="",
            category="bug", severity="low", title="t", description="d",
        )


# --------------------------- list / get / update --------------------------- #
def test_list_default_empty(isolated_repo):
    res = list_suggestions(isolated_repo)
    assert res["total"] == 0
    assert res["suggestions"] == []


def test_list_filters_by_target(isolated_repo):
    submit_suggestion(
        isolated_repo, source_agent="a", target_repo="platform-cdc",
        category="bug", severity="low", title="t", description="d",
    )
    submit_suggestion(
        isolated_repo, source_agent="a", target_repo="platform-ml",
        category="bug", severity="low", title="t", description="d",
    )
    res = list_suggestions(isolated_repo, target_repo="platform-cdc")
    assert res["total"] == 1
    assert res["suggestions"][0]["target_repo"] == "platform-cdc"


def test_list_filters_by_status(isolated_repo):
    r = submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="low", title="t", description="d",
    )
    submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="low", title="t2", description="d",
    )
    update_suggestion_status(isolated_repo, r["suggestion"]["id"], "accepted", by="caiog")
    res = list_suggestions(isolated_repo, status="accepted")
    assert res["total"] == 1
    assert res["suggestions"][0]["status"] == "accepted"


def test_list_filters_by_severity(isolated_repo):
    submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="critical", title="t", description="d",
    )
    submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="low", title="t", description="d",
    )
    res = list_suggestions(isolated_repo, severity="critical")
    assert res["total"] == 1
    assert res["suggestions"][0]["severity"] == "critical"


def test_list_resolves_alias_target_filter(isolated_repo):
    """Filtro target_repo='rag-service' deve casar a sugestão registrada como dataforall-rag-service."""
    submit_suggestion(
        isolated_repo, source_agent="a", target_repo="rag-service",
        category="bug", severity="low", title="t", description="d",
    )
    res = list_suggestions(isolated_repo, target_repo="rag-service")
    assert res["total"] == 1


def test_get_returns_full_payload(isolated_repo):
    r = submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="low", title="t", description="d",
    )
    res = get_suggestion(isolated_repo, suggestion_id=r["suggestion"]["id"])
    assert res["found"] is True
    assert res["suggestion"]["title"] == "t"


def test_get_returns_not_found(isolated_repo):
    res = get_suggestion(isolated_repo, suggestion_id="20260101T000000000000-deadbeef")
    assert res["found"] is False


def test_get_validates_id_format(isolated_repo):
    with pytest.raises(ValueError):
        get_suggestion(isolated_repo, suggestion_id="bogus")


def test_update_status_records_history(isolated_repo):
    r = submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="low", title="t", description="d",
    )
    sid = r["suggestion"]["id"]
    update_suggestion_status(isolated_repo, sid, "acknowledged", note="visto", by="caiog")
    update_suggestion_status(isolated_repo, sid, "accepted", note="vai virar PR", by="caiog")
    final = get_suggestion(isolated_repo, suggestion_id=sid)
    assert final["suggestion"]["status"] == "accepted"
    assert len(final["suggestion"]["status_history"]) == 3
    notes = [h["note"] for h in final["suggestion"]["status_history"] if h["note"]]
    assert "vai virar PR" in notes


def test_update_status_validates_status(isolated_repo):
    r = submit_suggestion(
        isolated_repo, source_agent="a", target_repo="x",
        category="bug", severity="low", title="t", description="d",
    )
    with pytest.raises(ValueError):
        update_suggestion_status(isolated_repo, r["suggestion"]["id"], "invalid-status")


# --------------------------- store unavailable --------------------------- #
def test_tools_raise_unavailable_when_store_missing():
    class _StubRepo:
        suggestions = None
        ecosystem = None
    stub = _StubRepo()
    with pytest.raises(SuggestionsUnavailable):
        submit_suggestion(
            stub, source_agent="a", target_repo="x",
            category="bug", severity="low", title="t", description="d",
        )
    with pytest.raises(SuggestionsUnavailable):
        list_suggestions(stub)
