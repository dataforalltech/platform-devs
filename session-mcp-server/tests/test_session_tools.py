"""Testes das ferramentas do session-mcp-server contra MySQL real (§16 / FID-02, async).

A camada de tools (validação + audit) roda sobre o ``SessionStore`` tenant-scoped
canônico. O fixture ``active_session`` é uma sessão viva no tenant A."""

from __future__ import annotations

import pytest

from src.tools.session_tool import (
    accept_suggestion,
    add_artifact,
    add_service_dependency,
    add_task,
    approve_task,
    cancel_task,
    complete_task,
    confirm_branch_created,
    defer_suggestion,
    end_session,
    fail_task,
    get_decision_tool,
    get_session,
    get_suggestion_tool,
    get_task,
    list_decisions_tool,
    list_service_dependencies,
    list_sessions,
    list_suggestions_tool,
    list_tasks,
    reject_suggestion,
    remove_service_dependency,
    resume_session,
    save_checkpoint,
    start_session,
    start_task,
    submit_suggestion,
    supersede_suggestion,
    update_session,
)

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]

_ACTOR_HUMAN = {"type": "human", "id": "test@dataforall.tech"}
_ACTOR_AGENT = {"type": "agent", "id": "sess_test"}
_COMMIT_KW = {"commit_sha": "abc123", "commit_message": "task: msg"}
_END_KW = {"actor": _ACTOR_HUMAN, "rationale": "test cleanup"}


# ── start_session ─────────────────────────────────────────────────────────────
async def test_start_session_with_branch_suggestion(store_a):
    result = await start_session(
        store_a, "develop", title="Refactor JWT", objective="Mover JWT", repo="platform-auth"
    )
    assert result["id"].startswith("sess_")
    assert result["repo"] == "platform-auth"
    assert result["status"] == "active"
    assert result["branch"].startswith("session/")
    assert result["base_branch"] == "develop"
    assert result["next_action"]["tool"] == "mcp__deploy-mcp__create_branch"
    assert result["next_action"]["args"]["repo"] == "platform-auth"
    assert result["next_action"]["args"]["from_ref"] == "develop"


async def test_start_session_custom_base_branch(store_a):
    result = await start_session(
        store_a, "develop", title="Fix", objective="NPE", repo="platform-api", base_branch="main"
    )
    assert result["base_branch"] == "main"
    assert result["next_action"]["args"]["from_ref"] == "main"


async def test_start_session_validation(store_a):
    assert (await start_session(store_a, "develop", title="", objective="o", repo="r"))[
        "error"
    ] == "ValidationError"
    assert (await start_session(store_a, "develop", title="t", objective="", repo="r"))[
        "error"
    ] == "ValidationError"
    missing_repo = await start_session(store_a, "develop", title="t", objective="o", repo="")
    assert missing_repo["error"] == "ValidationError"
    assert "repo" in missing_repo["details"].lower()


async def test_start_session_includes_pending_suggestions(store_a):
    await submit_suggestion(store_a, source_repo="x", target_repo="platform-target", title="s1")
    await submit_suggestion(store_a, source_repo="x", target_repo="platform-target", title="s2")
    session = await start_session(store_a, "develop", title="t", objective="o", repo="platform-target")
    assert session["pending_suggestions"]["count"] == 2
    titles = {s["title"] for s in session["pending_suggestions"]["items"]}
    assert titles == {"s1", "s2"}


# ── confirm_branch_created ────────────────────────────────────────────────────
async def test_confirm_branch_created(store_a, active_session):
    sid = active_session["id"]
    before = (await get_session(store_a, session_id=sid))["artifacts_count"]
    result = await confirm_branch_created(store_a, session_id=sid, sha="abcdef0")
    assert result["confirmed"] is True
    after = (await get_session(store_a, session_id=sid))["artifacts_count"]
    assert after == before + 1


async def test_confirm_branch_not_found(store_a):
    assert (await confirm_branch_created(store_a, session_id="sess_nope"))["error"] == "not_found"


# ── checkpoints ───────────────────────────────────────────────────────────────
async def test_save_checkpoint(store_a, active_session):
    sid = active_session["id"]
    result = await save_checkpoint(store_a, session_id=sid, summary="JWT extraído")
    assert result["session_id"] == sid
    assert "checkpoint_id" in result
    session = await get_session(store_a, session_id=sid)
    assert session["last_checkpoint"]["summary"] == "JWT extraído"


async def test_save_checkpoint_errors(store_a):
    assert (await save_checkpoint(store_a, session_id="", summary="x"))["error"] == "ValidationError"
    assert (await save_checkpoint(store_a, session_id="sess_nope", summary="x"))["error"] == "not_found"


# ── update / list / get ───────────────────────────────────────────────────────
async def test_update_session(store_a, active_session):
    sid = active_session["id"]
    assert (await update_session(store_a, session_id=sid, status="paused"))["status"] == "paused"
    assert (await update_session(store_a, session_id=sid, progress="50%"))["progress"] == "50%"
    assert (await update_session(store_a, session_id=sid, status="bad"))["error"] == "ValidationError"


async def test_list_sessions_filters(store_a):
    a = await store_a.create_session(title="A", objective="o", repo="r")
    await store_a.update_session(a["id"], status="completed")
    await store_a.create_session(title="B", objective="o", repo="r")
    active = await list_sessions(store_a, status="active")
    assert active["count"] == 1 and active["sessions"][0]["title"] == "B"
    assert (await list_sessions(store_a, status="unknown"))["error"] == "ValidationError"


async def test_get_session_errors(store_a):
    assert (await get_session(store_a, session_id=""))["error"] == "ValidationError"
    assert (await get_session(store_a, session_id="sess_nope"))["error"] == "not_found"


# ── artifacts ─────────────────────────────────────────────────────────────────
async def test_add_artifact(store_a, active_session):
    sid = active_session["id"]
    result = await add_artifact(store_a, session_id=sid, artifact_type="file_changed", content="x.py")
    assert result["type"] == "file_changed"
    assert (await add_artifact(store_a, session_id=sid, artifact_type="bad", content="x"))[
        "error"
    ] == "ValidationError"


# ── resume ────────────────────────────────────────────────────────────────────
async def test_resume_full_context(store_a, active_session):
    sid = active_session["id"]
    await save_checkpoint(store_a, session_id=sid, summary="estado")
    await add_artifact(store_a, session_id=sid, artifact_type="note", content="lembrete")
    result = await resume_session(store_a, session_id=sid)
    assert len(result["checkpoints"]) == 1
    assert len(result["recent_artifacts"]) == 1
    assert "Test Session" in result["resume_hint"]


async def test_resume_reactivates_paused(store_a, active_session):
    sid = active_session["id"]
    await store_a.update_session(sid, status="paused")
    result = await resume_session(store_a, session_id=sid)
    assert result["session"]["status"] == "active"


async def test_resume_warns_when_repo_missing(store_a):
    legacy = await store_a.create_session(title="Legacy", objective="obj", repo="")
    result = await resume_session(store_a, session_id=legacy["id"])
    assert any("REPO_MISSING" in w for w in result["warnings"])
    assert "REPO_MISSING" in result["resume_hint"]


async def test_resume_not_found(store_a):
    assert (await resume_session(store_a, session_id="sess_ghost"))["error"] == "not_found"


# ── end_session ───────────────────────────────────────────────────────────────
async def test_end_session_completes(store_a, active_session):
    sid = active_session["id"]
    result = await end_session(store_a, session_id=sid, **_END_KW)
    assert result["status"] == "completed"
    assert result["ended_at"] is not None


async def test_end_session_blocks_on_open_tasks(store_a, active_session):
    sid = active_session["id"]
    await add_task(store_a, session_id=sid, title="pend")
    result = await end_session(store_a, session_id=sid, **_END_KW)
    assert result["error"] == "open_tasks"
    assert (await get_session(store_a, session_id=sid))["status"] == "active"


async def test_end_session_requires_actor_and_rationale(store_a, active_session):
    sid = active_session["id"]
    assert (await end_session(store_a, session_id=sid, actor=None, rationale="x"))[
        "error"
    ] == "ValidationError"
    assert (await end_session(store_a, session_id=sid, actor=_ACTOR_HUMAN, rationale=""))[
        "error"
    ] == "ValidationError"


# ── tasks ─────────────────────────────────────────────────────────────────────
async def test_add_task_single_and_bulk(store_a, active_session):
    sid = active_session["id"]
    single = await add_task(store_a, session_id=sid, title="login", description="JWT")
    assert single["title"] == "login" and single["status"] == "pending"
    bulk = await add_task(store_a, session_id=sid, tasks=[{"title": "a"}, {"title": "b"}])
    assert bulk["count"] == 2


async def test_add_task_validation(store_a, active_session):
    sid = active_session["id"]
    assert (await add_task(store_a, session_id=sid))["error"] == "ValidationError"
    assert (await add_task(store_a, session_id=sid, tasks=[]))["error"] == "ValidationError"
    assert (await add_task(store_a, session_id="sess_nope", title="x"))["error"] == "not_found"


async def test_complete_task_records_commit(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="t")
    result = await complete_task(
        store_a, task_id=task["id"], commit_sha="deadbeef", commit_message="task: t", result="ok"
    )
    assert result["status"] == "completed" and result["commit_sha"] == "deadbeef"


async def test_complete_task_requires_commit(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="t")
    assert (await complete_task(store_a, task_id=task["id"], commit_sha="", commit_message="m"))[
        "error"
    ] == "ValidationError"


async def test_start_task_invalid_transition(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="t")
    await complete_task(store_a, task_id=task["id"], **_COMMIT_KW)
    result = await start_task(store_a, task_id=task["id"])
    assert result["error"] == "invalid_transition"
    assert result["current_status"] == "completed"


async def test_fail_and_cancel_task(store_a, active_session):
    sid = active_session["id"]
    t1 = await add_task(store_a, session_id=sid, title="a")
    t2 = await add_task(store_a, session_id=sid, title="b")
    assert (await fail_task(store_a, task_id=t1["id"], actor=_ACTOR_AGENT, reason="lib"))[
        "status"
    ] == "failed"
    assert (await cancel_task(store_a, task_id=t2["id"], actor=_ACTOR_HUMAN, reason="scope"))[
        "status"
    ] == "cancelled"
    assert (await cancel_task(store_a, task_id=t2["id"], actor=_ACTOR_HUMAN, reason=""))[
        "error"
    ] == "ValidationError"


async def test_list_and_get_task(store_a, active_session):
    sid = active_session["id"]
    t1 = await add_task(store_a, session_id=sid, title="a")
    await add_task(store_a, session_id=sid, title="b")
    await complete_task(store_a, task_id=t1["id"], **_COMMIT_KW)
    pending = await list_tasks(store_a, session_id=sid, status="pending")
    assert pending["count"] == 1 and pending["tasks"][0]["title"] == "b"
    assert (await get_task(store_a, task_id=t1["id"]))["id"] == t1["id"]
    assert (await get_task(store_a, task_id=999999))["error"] == "not_found"


# ── needs_human_decision ──────────────────────────────────────────────────────
async def test_needs_human_decision_flow(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="risky", needs_human_decision=True)
    assert task["needs_human_decision"] == 1
    blocked = await start_task(store_a, task_id=task["id"])
    assert blocked["error"] == "human_decision_pending"

    approval = await approve_task(
        store_a, task_id=task["id"], decision="go", actor=_ACTOR_HUMAN, rationale="reviewed"
    )
    assert approval["decision"] == "go"
    assert (await start_task(store_a, task_id=task["id"]))["status"] == "in_progress"


async def test_no_go_cancels_and_requires_rationale(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="x", needs_human_decision=True)
    assert (await approve_task(store_a, task_id=task["id"], decision="no_go", actor=_ACTOR_HUMAN))[
        "error"
    ] == "ValidationError"
    result = await approve_task(
        store_a, task_id=task["id"], decision="no_go", actor=_ACTOR_HUMAN, rationale="danger"
    )
    assert result["status"] == "cancelled"


# ── service dependencies ──────────────────────────────────────────────────────
async def test_service_dependency_tools(store_a, active_session):
    sid = active_session["id"]
    linked = await add_service_dependency(store_a, session_id=sid, service="postgres", role="database")
    assert linked["service"] == "postgres"
    assert (await add_service_dependency(store_a, session_id=sid, service="postgres"))["error"] == "duplicate"
    listed = await list_service_dependencies(store_a, session_id=sid)
    assert listed["count"] == 1
    assert (await remove_service_dependency(store_a, session_id=sid, service="postgres"))["removed"] is True
    assert (await remove_service_dependency(store_a, session_id=sid, service="ghost"))["error"] == "not_found"


# ── cross-repo suggestions ────────────────────────────────────────────────────
async def test_submit_and_list_suggestions(store_a):
    result = await submit_suggestion(
        store_a,
        source_repo="platform-dai",
        target_repo="platform-auth",
        title="refresh token",
        kind="addition",
        priority="high",
    )
    assert result["status"] == "pending"
    assert result["needs_human_decision"] is True
    assert (await submit_suggestion(store_a, source_repo="a", target_repo="b", title="t", kind="bad"))[
        "error"
    ] == "ValidationError"
    listed = await list_suggestions_tool(store_a, target_repo="platform-auth")
    assert listed["count"] == 1


async def test_accept_suggestion_creates_task(store_a, active_session):
    s = await submit_suggestion(
        store_a, source_repo="platform-dai", target_repo=active_session["repo"], title="Refactor lib"
    )
    result = await accept_suggestion(
        store_a,
        suggestion_id=s["id"],
        session_id=active_session["id"],
        actor=_ACTOR_HUMAN,
        rationale="approved",
    )
    assert result["suggestion"]["status"] == "accepted"
    assert result["task"]["title"] == "Refactor lib"
    assert result["task"]["needs_human_decision"] == 1
    assert "[suggestion #" in (result["task"]["description"] or "")


async def test_accept_suggestion_repo_mismatch(store_a, active_session):
    s = await submit_suggestion(store_a, source_repo="o", target_repo="some-other-repo", title="x")
    result = await accept_suggestion(
        store_a, suggestion_id=s["id"], session_id=active_session["id"], actor=_ACTOR_HUMAN
    )
    assert result["error"] == "ValidationError"


async def test_reject_defer_supersede(store_a):
    s = await submit_suggestion(store_a, source_repo="x", target_repo="y", title="t")
    assert (await reject_suggestion(store_a, suggestion_id=s["id"], actor=_ACTOR_HUMAN, reason="dup"))[
        "status"
    ] == "rejected"

    d = await submit_suggestion(store_a, source_repo="x", target_repo="y", title="d")
    assert (await defer_suggestion(store_a, suggestion_id=d["id"], actor=_ACTOR_HUMAN))[
        "status"
    ] == "deferred"

    old = await submit_suggestion(store_a, source_repo="x", target_repo="y", title="old")
    new = await submit_suggestion(store_a, source_repo="x", target_repo="y", title="new")
    sup = await supersede_suggestion(
        store_a, suggestion_id=old["id"], actor=_ACTOR_AGENT, by_suggestion_id=new["id"]
    )
    assert sup["status"] == "superseded" and sup["superseded_by"] == new["id"]


async def test_get_suggestion(store_a):
    s = await submit_suggestion(store_a, source_repo="x", target_repo="y", title="t")
    assert (await get_suggestion_tool(store_a, suggestion_id=s["id"]))["title"] == "t"
    assert (await get_suggestion_tool(store_a, suggestion_id=999999))["error"] == "not_found"


# ── decisions audit ───────────────────────────────────────────────────────────
async def test_approve_records_decision(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="x", needs_human_decision=True)
    await approve_task(store_a, task_id=task["id"], decision="go", actor=_ACTOR_HUMAN, rationale="ok")
    decisions = await list_decisions_tool(store_a, target_type="task", target_id=str(task["id"]))
    assert decisions["count"] == 1
    d = decisions["decisions"][0]
    assert d["actor_type"] == "human" and d["action"] == "approve_task" and d["decision"] == "go"


async def test_cancel_records_decision_and_get(store_a, active_session):
    sid = active_session["id"]
    task = await add_task(store_a, session_id=sid, title="x")
    await cancel_task(store_a, task_id=task["id"], actor=_ACTOR_AGENT, reason="abandoned")
    decisions = await list_decisions_tool(store_a, action="cancel_task")
    assert decisions["count"] == 1
    d_id = decisions["decisions"][0]["id"]
    assert (await get_decision_tool(store_a, decision_id=d_id))["rationale"] == "abandoned"
    assert (await get_decision_tool(store_a, decision_id=999999))["error"] == "not_found"


async def test_list_decisions_invalid_actor_type(store_a):
    assert (await list_decisions_tool(store_a, actor_type="alien"))["error"] == "ValidationError"
