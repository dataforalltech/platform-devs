"""Store canônico contra MySQL real (§16 / FID-02): CRUD, transições, upsert de chave
natural, soft-delete + reativação, agregações e ISOLAMENTO por tenant (banco-por-tenant)."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


async def _mk_session(store, repo="platform-x"):
    s = await store.create_session(title="T", objective="O", repo=repo)
    return s["id"]


# ── Sessions ──────────────────────────────────────────────────────────────────
async def test_create_session_maps_business_key_to_id(store_a):
    s = await store_a.create_session(title="Refactor", objective="mover JWT", repo="platform-auth")
    assert s["id"].startswith("sess_")
    assert "session_uid" not in s  # a chave de negócio é exposta como 'id'
    assert s["repo"] == "platform-auth"
    assert s["status"] == "active"
    assert s["tasks_summary"]["total"] == 0
    assert s["artifacts_count"] == 0
    assert s["service_dependencies"] == []


async def test_get_session_none_when_absent(store_a):
    assert await store_a.get_session("sess_nope") is None


async def test_set_branch_and_get(store_a):
    sid = await _mk_session(store_a)
    await store_a.set_session_branch(sid, branch="session/x", base_branch="develop")
    got = await store_a.get_session(sid)
    assert got["branch"] == "session/x"
    assert got["base_branch"] == "develop"


async def test_list_sessions_filters(store_a):
    a = await store_a.create_session(title="A", objective="o", repo="platform-api")
    await store_a.create_session(title="B", objective="o", repo="platform-auth")
    await store_a.update_session(a["id"], status="completed")

    assert len(await store_a.list_sessions()) == 2
    assert {s["title"] for s in await store_a.list_sessions(status="active")} == {"B"}
    assert {s["title"] for s in await store_a.list_sessions(repo="platform-api")} == {"A"}


async def test_update_session_none_when_absent(store_a):
    assert await store_a.update_session("sess_nope", status="paused") is None


async def test_end_session_blocks_on_open_tasks_then_completes(store_a):
    sid = await _mk_session(store_a)
    t = await store_a.create_task(sid, title="pend")
    blocked = await store_a.end_session(sid, summary="fim")
    assert isinstance(blocked, list) and len(blocked) == 1

    await store_a.complete_task(t["id"], commit_sha="sha", commit_message="m")
    ended = await store_a.end_session(sid, summary="tudo certo")
    assert ended["status"] == "completed"
    assert ended["ended_at"] is not None
    assert "[FINAL]" in ended["last_checkpoint"]["summary"]


async def test_end_session_none_when_absent(store_a):
    assert await store_a.end_session("sess_nope") is None


# ── Checkpoints / artifacts ───────────────────────────────────────────────────
async def test_checkpoints_recorded_and_listed(store_a):
    sid = await _mk_session(store_a)
    cp = await store_a.save_checkpoint(sid, summary="cp1", context={"next": "x"})
    assert isinstance(cp["checkpoint_id"], int)
    await store_a.save_checkpoint(sid, summary="cp2")
    listed = await store_a.list_checkpoints(sid)
    assert [c["summary"] for c in listed] == ["cp2", "cp1"]  # id DESC
    session = await store_a.get_session(sid)
    assert session["last_checkpoint"]["summary"] == "cp2"


async def test_artifacts_recorded_counted_filtered(store_a):
    sid = await _mk_session(store_a)
    await store_a.add_artifact(sid, "note", "n1")
    await store_a.add_artifact(sid, "file_changed", "src/x.py")
    session = await store_a.get_session(sid)
    assert session["artifacts_count"] == 2
    notes = await store_a.list_artifacts(sid, artifact_type="note")
    assert len(notes) == 1 and notes[0]["type"] == "note"


# ── Tasks ─────────────────────────────────────────────────────────────────────
async def test_task_lifecycle_and_ordering(store_a):
    sid = await _mk_session(store_a)
    await store_a.create_task(sid, title="first")
    bulk = await store_a.create_tasks(sid, [{"title": "second"}, {"title": "third"}])
    assert len(bulk) == 2
    listed = await store_a.list_tasks(sid)
    assert [t["title"] for t in listed] == ["first", "second", "third"]  # sort_order preservado


async def test_task_transitions(store_a):
    sid = await _mk_session(store_a)
    t = await store_a.create_task(sid, title="t")
    started = await store_a.start_task(t["id"])
    assert started["status"] == "in_progress"
    assert started["started_at"] is not None
    done = await store_a.complete_task(t["id"], commit_sha="deadbeef", commit_message="msg", result="ok")
    assert done["status"] == "completed"
    assert done["commit_sha"] == "deadbeef"
    # transição inválida devolve o status atual (string)
    assert await store_a.start_task(t["id"]) == "completed"
    assert await store_a.start_task(999999) is None


async def test_task_fail_and_cancel(store_a):
    sid = await _mk_session(store_a)
    t1 = await store_a.create_task(sid, title="a")
    t2 = await store_a.create_task(sid, title="b")
    assert (await store_a.fail_task(t1["id"], reason="boom"))["status"] == "failed"
    cancelled = await store_a.cancel_task(t2["id"], reason="drop")
    assert cancelled["status"] == "cancelled"
    assert cancelled["result"] == "drop"


async def test_task_summary_counts(store_a):
    sid = await _mk_session(store_a)
    t1 = await store_a.create_task(sid, title="a")
    await store_a.create_task(sid, title="b")
    await store_a.complete_task(t1["id"], commit_sha="s", commit_message="m")
    session = await store_a.get_session(sid)
    assert session["tasks_summary"]["total"] == 2
    assert session["tasks_summary"]["completed"] == 1
    assert session["tasks_summary"]["pending"] == 1


async def test_approve_task_go_and_no_go(store_a):
    sid = await _mk_session(store_a)
    t = await store_a.create_task(sid, title="risky", needs_human_decision=True)
    assert t["needs_human_decision"] == 1
    # start bloqueia até decisão (no store isso é responsabilidade da tool; aqui checamos o go)
    go = await store_a.approve_task(t["id"], decision="go", notes="reviewed")
    assert go["decision"] == "go" and go["status"] == "pending"

    t2 = await store_a.create_task(sid, title="risky2", needs_human_decision=True)
    no_go = await store_a.approve_task(t2["id"], decision="no_go", notes="too risky")
    assert no_go["status"] == "cancelled" and no_go["decision"] == "no_go"
    assert "too risky" in no_go["result"]
    # já não é pending -> devolve status atual
    assert await store_a.approve_task(t2["id"], decision="go") == "cancelled"


async def test_approve_task_invalid_decision_raises(store_a):
    sid = await _mk_session(store_a)
    t = await store_a.create_task(sid, title="x", needs_human_decision=True)
    with pytest.raises(ValueError):
        await store_a.approve_task(t["id"], decision="maybe")


# ── Service dependencies (upsert de chave natural + soft-delete/reativação) ────
async def test_service_dep_add_duplicate_remove_reactivate(store_a):
    sid = await _mk_session(store_a)
    added = await store_a.add_service_dependency(sid, service="postgres", role="database")
    assert added["service"] == "postgres" and added["role"] == "database"
    assert await store_a.add_service_dependency(sid, service="postgres") == "duplicate"

    removed = await store_a.remove_service_dependency(sid, service="postgres")
    assert removed is True
    assert await store_a.list_service_dependencies(sid) == []
    # remover de novo (linha já soft-deletada) -> False
    assert await store_a.remove_service_dependency(sid, service="postgres") is False

    # re-adicionar reativa a linha soft-deletada (mesma chave única, sem violar UNIQUE)
    reactivated = await store_a.add_service_dependency(sid, service="postgres", role="db2")
    assert reactivated["role"] == "db2"
    assert len(await store_a.list_service_dependencies(sid)) == 1


async def test_service_dep_session_absent(store_a):
    assert await store_a.add_service_dependency("sess_nope", service="x") is None
    assert await store_a.list_service_dependencies("sess_nope") is None
    assert await store_a.remove_service_dependency("sess_nope", service="x") is None


# ── Suggestions (fila cross-repo + transições) ────────────────────────────────
async def test_suggestion_create_list_count(store_a):
    await store_a.create_suggestion(source_repo="x", target_repo="A", title="a1")
    await store_a.create_suggestion(source_repo="x", target_repo="B", title="b1")
    assert len(await store_a.list_suggestions(target_repo="A")) == 1
    assert await store_a.count_pending_suggestions("A") == 1
    assert await store_a.count_pending_suggestions("Z") == 0


async def test_suggestion_transitions(store_a):
    s = await store_a.create_suggestion(source_repo="x", target_repo="y", title="t")
    rejected = await store_a.transition_suggestion(s["id"], new_status="rejected", response_reason="dup")
    assert rejected["status"] == "rejected" and rejected["response_reason"] == "dup"
    # já respondida -> só pending transita
    assert await store_a.transition_suggestion(s["id"], new_status="deferred") == "rejected"
    assert await store_a.transition_suggestion(999999, new_status="deferred") is None


async def test_suggestion_accept_flow_via_store(store_a):
    sid = await _mk_session(store_a, repo="target-repo")
    s = await store_a.create_suggestion(source_repo="src", target_repo="target-repo", title="do it")
    task = await store_a.create_task(sid, title=s["title"], needs_human_decision=True)
    transitioned = await store_a.transition_suggestion(
        s["id"], new_status="accepted", accepted_session_id=sid, accepted_task_id=task["id"]
    )
    assert transitioned["status"] == "accepted"
    assert transitioned["accepted_task_id"] == task["id"]


# ── Decisions (audit trail) ───────────────────────────────────────────────────
async def test_record_and_query_decisions(store_a):
    d = await store_a.record_decision(
        actor_type="human",
        actor_id="dev@x.tech",
        action="approve_task",
        target_type="task",
        target_id="1",
        decision="go",
        rationale="ok",
        context={"k": "v"},
    )
    assert d["actor_type"] == "human"
    got = await store_a.get_decision(d["id"])
    assert got["decision"] == "go"
    assert len(await store_a.list_decisions(action="approve_task")) == 1
    assert len(await store_a.list_decisions(actor_type="agent")) == 0
    assert await store_a.get_decision(999999) is None


# ── Resume ────────────────────────────────────────────────────────────────────
async def test_resume_context_aggregates(store_a):
    sid = await _mk_session(store_a, repo="platform-x")
    await store_a.save_checkpoint(sid, summary="estado atual")
    await store_a.add_artifact(sid, "note", "lembrete")
    await store_a.create_task(sid, title="implementar X")
    ctx = await store_a.get_resume_context(sid)
    assert ctx["session"]["id"] == sid
    assert len(ctx["checkpoints"]) == 1
    assert len(ctx["recent_artifacts"]) == 1
    assert len(ctx["open_tasks"]) == 1
    assert "implementar X" in ctx["resume_hint"]
    assert ctx["warnings"] == []


async def test_resume_none_when_absent(store_a):
    assert await store_a.get_resume_context("sess_ghost") is None


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    a = await store_a.create_session(title="only-a", objective="o", repo="r")
    assert len(await store_a.list_sessions()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_sessions() == []
    assert await store_b.get_session(a["id"]) is None
