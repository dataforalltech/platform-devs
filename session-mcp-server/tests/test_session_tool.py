"""Testes para as ferramentas do session-mcp-server."""

from __future__ import annotations

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
    get_session,
    get_suggestion_tool,
    get_task,
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

_ACTOR_HUMAN = {"type": "human", "id": "test@dataforall.tech"}
_ACTOR_AGENT = {"type": "agent", "id": "sess_test"}


class TestStartSession:
    def test_creates_session_with_branch_suggestion(self, store):
        result = start_session(
            store,
            "develop",
            title="Refactor JWT",
            objective="Mover JWT para lib",
            repo="platform-auth",
        )
        assert result["id"].startswith("sess_")
        assert result["repo"] == "platform-auth"
        assert result["status"] == "active"
        assert result["branch"].startswith("session/")
        assert result["base_branch"] == "develop"
        assert result["next_action"]["tool"] == "mcp__deploy-mcp__create_branch"
        assert result["next_action"]["args"]["repo"] == "platform-auth"
        assert result["next_action"]["args"]["branch"] == result["branch"]
        assert result["next_action"]["args"]["from_ref"] == "develop"

    def test_uses_custom_base_branch(self, store):
        result = start_session(
            store, "develop",
            title="Fix bug", objective="Corrigir NPE",
            repo="platform-api", base_branch="main",
        )
        assert result["base_branch"] == "main"
        assert result["next_action"]["args"]["from_ref"] == "main"

    def test_missing_title_returns_error(self, store):
        result = start_session(
            store, "develop",
            title="", objective="algum objetivo", repo="platform-api",
        )
        assert result["error"] == "ValidationError"

    def test_missing_objective_returns_error(self, store):
        result = start_session(
            store, "develop",
            title="algum título", objective="", repo="platform-api",
        )
        assert result["error"] == "ValidationError"

    def test_missing_repo_returns_error(self, store):
        result = start_session(store, "develop", title="t", objective="o", repo="")
        assert result["error"] == "ValidationError"
        assert "repo" in result["details"].lower()


class TestConfirmBranchCreated:
    def test_confirms_with_artifact(self, store, active_session):
        sid = active_session["id"]
        before = get_session(store, session_id=sid)["artifacts_count"]
        result = confirm_branch_created(store, session_id=sid, sha="abcdef0")
        assert result["confirmed"] is True
        assert result["branch"].startswith("session/")
        after = get_session(store, session_id=sid)["artifacts_count"]
        assert after == before + 1

    def test_confirms_without_sha(self, store, active_session):
        sid = active_session["id"]
        result = confirm_branch_created(store, session_id=sid)
        assert result["confirmed"] is True

    def test_session_not_found(self, store):
        result = confirm_branch_created(store, session_id="sess_nope")
        assert result["error"] == "not_found"


class TestSaveCheckpoint:
    def test_saves_checkpoint_with_summary(self, store, active_session):
        sid = active_session["id"]
        result = save_checkpoint(store, session_id=sid, summary="JWT extraído, faltam os testes")
        assert result["session_id"] == sid
        assert result["summary"] == "JWT extraído, faltam os testes"
        assert "checkpoint_id" in result

    def test_saves_checkpoint_with_context(self, store, active_session):
        sid = active_session["id"]
        ctx = {"pending_files": ["tests/test_jwt.py"], "next_step": "atualizar imports"}
        result = save_checkpoint(store, session_id=sid, summary="Ponto de controle", context=ctx)
        assert "checkpoint_id" in result

    def test_checkpoint_appears_in_session(self, store, active_session):
        sid = active_session["id"]
        save_checkpoint(store, session_id=sid, summary="checkpoint 1")
        session = get_session(store, session_id=sid)
        assert session["last_checkpoint"]["summary"] == "checkpoint 1"

    def test_missing_session_id_returns_error(self, store):
        result = save_checkpoint(store, session_id="", summary="algo")
        assert result["error"] == "ValidationError"

    def test_nonexistent_session_returns_not_found(self, store):
        result = save_checkpoint(store, session_id="sess_nope", summary="algo")
        assert result["error"] == "not_found"


class TestUpdateSession:
    def test_updates_status_to_paused(self, store, active_session):
        sid = active_session["id"]
        result = update_session(store, session_id=sid, status="paused")
        assert result["status"] == "paused"

    def test_updates_progress_text(self, store, active_session):
        sid = active_session["id"]
        result = update_session(store, session_id=sid, progress="50% concluído")
        assert result["progress"] == "50% concluído"

    def test_invalid_status_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = update_session(store, session_id=sid, status="working")
        assert result["error"] == "ValidationError"

    def test_missing_session_id_returns_error(self, store):
        result = update_session(store, session_id="")
        assert result["error"] == "ValidationError"


class TestAddArtifact:
    def test_adds_file_changed_artifact(self, store, active_session):
        sid = active_session["id"]
        result = add_artifact(
            store,
            session_id=sid,
            artifact_type="file_changed",
            content="src/auth/jwt.py",
        )
        assert result["artifact_id"] is not None
        assert result["type"] == "file_changed"

    def test_adds_decision_artifact(self, store, active_session):
        sid = active_session["id"]
        result = add_artifact(
            store,
            session_id=sid,
            artifact_type="decision",
            content="Usar HS256 em vez de RS256 para simplificar deploy",
        )
        assert result["type"] == "decision"

    def test_invalid_artifact_type_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = add_artifact(store, session_id=sid, artifact_type="invalid_type", content="x")
        assert result["error"] == "ValidationError"

    def test_artifacts_count_increases(self, store, active_session):
        sid = active_session["id"]
        add_artifact(store, session_id=sid, artifact_type="note", content="nota 1")
        add_artifact(store, session_id=sid, artifact_type="note", content="nota 2")
        session = get_session(store, session_id=sid)
        assert session["artifacts_count"] == 2


class TestListSessions:
    def test_lists_all_sessions(self, store):
        store.create_session(title="S1", objective="obj1", repo="r1")
        store.create_session(title="S2", objective="obj2", repo="r2")
        result = list_sessions(store)
        assert result["count"] == 2

    def test_filters_by_status(self, store):
        s1 = store.create_session(title="A", objective="obj", repo="r")
        store.update_session(s1["id"], status="completed")
        store.create_session(title="B", objective="obj", repo="r")
        result = list_sessions(store, status="active")
        assert result["count"] == 1
        assert result["sessions"][0]["title"] == "B"

    def test_filters_by_repo(self, store):
        store.create_session(title="S1", objective="o", repo="platform-api")
        store.create_session(title="S2", objective="o", repo="platform-auth")
        result = list_sessions(store, repo="platform-api")
        assert result["count"] == 1

    def test_invalid_status_returns_error(self, store):
        result = list_sessions(store, status="unknown")
        assert result["error"] == "ValidationError"


class TestGetSession:
    def test_returns_full_session(self, store, active_session):
        sid = active_session["id"]
        result = get_session(store, session_id=sid)
        assert result["id"] == sid
        assert "last_checkpoint" in result
        assert "artifacts_count" in result

    def test_missing_session_id_returns_error(self, store):
        result = get_session(store, session_id="")
        assert result["error"] == "ValidationError"

    def test_not_found_returns_error(self, store):
        result = get_session(store, session_id="sess_nope")
        assert result["error"] == "not_found"


class TestResumeSession:
    def test_returns_full_context(self, store, active_session):
        sid = active_session["id"]
        save_checkpoint(store, session_id=sid, summary="estado atual")
        add_artifact(store, session_id=sid, artifact_type="note", content="lembrete")

        result = resume_session(store, session_id=sid)
        assert "session" in result
        assert "checkpoints" in result
        assert "recent_artifacts" in result
        assert "resume_hint" in result
        assert len(result["checkpoints"]) == 1
        assert len(result["recent_artifacts"]) == 1

    def test_reactivates_paused_session(self, store, active_session):
        sid = active_session["id"]
        store.update_session(sid, status="paused")
        result = resume_session(store, session_id=sid)
        assert result["session"]["status"] == "active"

    def test_resume_hint_contains_session_info(self, store, active_session):
        sid = active_session["id"]
        result = resume_session(store, session_id=sid)
        hint = result["resume_hint"]
        assert "Test Session" in hint
        assert "Testar o session-mcp-server" in hint

    def test_not_found_returns_error(self, store):
        result = resume_session(store, session_id="sess_ghost")
        assert result["error"] == "not_found"


_END_KW = {"actor": _ACTOR_HUMAN, "rationale": "test cleanup"}


class TestEndSession:
    def test_ends_session_with_status_completed(self, store, active_session):
        sid = active_session["id"]
        result = end_session(store, session_id=sid, **_END_KW)
        assert result["status"] == "completed"
        assert result["ended_at"] is not None

    def test_saves_final_checkpoint_when_summary_provided(self, store, active_session):
        sid = active_session["id"]
        end_session(
            store,
            session_id=sid,
            final_summary="JWT migrado com sucesso, todos os testes passando",
            **_END_KW,
        )
        session = get_session(store, session_id=sid)
        assert "[FINAL]" in session["last_checkpoint"]["summary"]

    def test_missing_session_id_returns_error(self, store):
        result = end_session(store, session_id="", **_END_KW)
        assert result["error"] == "ValidationError"

    def test_not_found_returns_error(self, store):
        result = end_session(store, session_id="sess_gone", **_END_KW)
        assert result["error"] == "not_found"

    def test_blocks_when_open_tasks_exist(self, store, active_session):
        sid = active_session["id"]
        add_task(store, session_id=sid, title="pendência")
        result = end_session(store, session_id=sid, **_END_KW)
        assert result["error"] == "open_tasks"
        assert len(result["open_tasks"]) == 1
        # Sessão NÃO foi encerrada
        session = get_session(store, session_id=sid)
        assert session["status"] == "active"

    def test_allows_close_after_tasks_resolved(self, store, active_session):
        sid = active_session["id"]
        t1 = add_task(store, session_id=sid, title="t1")
        t2 = add_task(store, session_id=sid, title="t2")
        complete_task(
            store,
            task_id=t1["id"],
            commit_sha="sha1",
            commit_message="task #x: t1",
        )
        cancel_task(
            store,
            task_id=t2["id"],
            actor=_ACTOR_HUMAN,
            reason="não é mais necessária",
        )
        result = end_session(store, session_id=sid, **_END_KW)
        assert result["status"] == "completed"

    def test_missing_actor_blocks(self, store, active_session):
        result = end_session(
            store, session_id=active_session["id"], actor=None, rationale="x"
        )
        assert result["error"] == "ValidationError"

    def test_missing_rationale_blocks(self, store, active_session):
        result = end_session(store, session_id=active_session["id"], actor=_ACTOR_HUMAN, rationale="")
        assert result["error"] == "ValidationError"


# ────────────────────────────────────────────────────────────────────────────── #
# Tasks                                                                       #
# ────────────────────────────────────────────────────────────────────────────── #


class TestAddTask:
    def test_creates_single_task(self, store, active_session):
        sid = active_session["id"]
        result = add_task(store, session_id=sid, title="Implementar login", description="Usar JWT")
        assert result["id"] is not None
        assert result["title"] == "Implementar login"
        assert result["description"] == "Usar JWT"
        assert result["status"] == "pending"
        assert result["session_id"] == sid

    def test_creates_bulk_tasks(self, store, active_session):
        sid = active_session["id"]
        result = add_task(
            store,
            session_id=sid,
            tasks=[
                {"title": "tarefa A"},
                {"title": "tarefa B", "description": "com descrição"},
                {"title": "tarefa C"},
            ],
        )
        assert result["count"] == 3
        assert result["tasks"][1]["description"] == "com descrição"
        assert all(t["status"] == "pending" for t in result["tasks"])

    def test_bulk_preserves_order(self, store, active_session):
        sid = active_session["id"]
        add_task(store, session_id=sid, title="primeiro")
        add_task(
            store,
            session_id=sid,
            tasks=[{"title": "segundo"}, {"title": "terceiro"}],
        )
        listed = list_tasks(store, session_id=sid)
        titles = [t["title"] for t in listed["tasks"]]
        assert titles == ["primeiro", "segundo", "terceiro"]

    def test_missing_title_and_tasks_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = add_task(store, session_id=sid)
        assert result["error"] == "ValidationError"

    def test_empty_tasks_list_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = add_task(store, session_id=sid, tasks=[])
        assert result["error"] == "ValidationError"

    def test_bulk_item_without_title_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = add_task(store, session_id=sid, tasks=[{"description": "sem title"}])
        assert result["error"] == "ValidationError"

    def test_session_not_found_returns_error(self, store):
        result = add_task(store, session_id="sess_nope", title="x")
        assert result["error"] == "not_found"


_COMMIT_KW = {"commit_sha": "abc123", "commit_message": "task: msg"}


class TestStartTask:
    def test_pending_to_in_progress(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = start_task(store, task_id=task["id"])
        assert result["status"] == "in_progress"
        assert result["started_at"] is not None

    def test_invalid_transition_from_completed(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        complete_task(store, task_id=task["id"], **_COMMIT_KW)
        result = start_task(store, task_id=task["id"])
        assert result["error"] == "invalid_transition"
        assert result["current_status"] == "completed"

    def test_not_found_returns_error(self, store):
        result = start_task(store, task_id=999)
        assert result["error"] == "not_found"


class TestCompleteTask:
    def test_records_commit_sha(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = complete_task(
            store,
            task_id=task["id"],
            commit_sha="deadbeef",
            commit_message="task #x: t",
            result="ok",
        )
        assert result["status"] == "completed"
        assert result["commit_sha"] == "deadbeef"
        assert result["commit_message"] == "task #x: t"
        assert result["result"] == "ok"
        assert result["completed_at"] is not None

    def test_in_progress_to_completed(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        start_task(store, task_id=task["id"])
        result = complete_task(store, task_id=task["id"], **_COMMIT_KW)
        assert result["status"] == "completed"

    def test_cannot_complete_cancelled(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        cancel_task(store, task_id=task["id"], actor=_ACTOR_HUMAN, reason="dropped")
        result = complete_task(store, task_id=task["id"], **_COMMIT_KW)
        assert result["error"] == "invalid_transition"

    def test_missing_commit_sha_blocks(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = complete_task(
            store,
            task_id=task["id"],
            commit_sha="",
            commit_message="msg",
        )
        assert result["error"] == "ValidationError"

    def test_missing_commit_message_blocks(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = complete_task(
            store,
            task_id=task["id"],
            commit_sha="sha",
            commit_message="",
        )
        assert result["error"] == "ValidationError"

    def test_not_found_returns_error(self, store):
        result = complete_task(store, task_id=999, **_COMMIT_KW)
        assert result["error"] == "not_found"


class TestFailTask:
    def test_marks_failed_with_reason(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = fail_task(
            store, task_id=task["id"], actor=_ACTOR_AGENT, reason="biblioteca não suporta"
        )
        assert result["status"] == "failed"
        assert result["result"] == "biblioteca não suporta"

    def test_missing_reason_returns_error(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = fail_task(store, task_id=task["id"], actor=_ACTOR_AGENT, reason="")
        assert result["error"] == "ValidationError"

    def test_missing_actor_returns_error(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = fail_task(store, task_id=task["id"], actor=None, reason="x")
        assert result["error"] == "ValidationError"


class TestCancelTask:
    def test_cancels_with_reason(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = cancel_task(
            store, task_id=task["id"], actor=_ACTOR_HUMAN, reason="escopo mudou"
        )
        assert result["status"] == "cancelled"
        assert result["result"] == "escopo mudou"

    def test_cancels_requires_reason(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = cancel_task(store, task_id=task["id"], actor=_ACTOR_HUMAN, reason="")
        assert result["error"] == "ValidationError"


class TestListTasks:
    def test_lists_all_tasks(self, store, active_session):
        sid = active_session["id"]
        add_task(store, session_id=sid, tasks=[{"title": "a"}, {"title": "b"}, {"title": "c"}])
        result = list_tasks(store, session_id=sid)
        assert result["count"] == 3

    def test_filters_by_status(self, store, active_session):
        sid = active_session["id"]
        t1 = add_task(store, session_id=sid, title="a")
        add_task(store, session_id=sid, title="b")
        complete_task(store, task_id=t1["id"], **_COMMIT_KW)
        result = list_tasks(store, session_id=sid, status="pending")
        assert result["count"] == 1
        assert result["tasks"][0]["title"] == "b"

    def test_invalid_status_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = list_tasks(store, session_id=sid, status="weird")
        assert result["error"] == "ValidationError"

    def test_session_not_found_returns_error(self, store):
        result = list_tasks(store, session_id="sess_nope")
        assert result["error"] == "not_found"


class TestGetTask:
    def test_returns_task(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="t")
        result = get_task(store, task_id=task["id"])
        assert result["id"] == task["id"]
        assert result["title"] == "t"

    def test_not_found_returns_error(self, store):
        result = get_task(store, task_id=12345)
        assert result["error"] == "not_found"


class TestTasksSummaryAndResume:
    def test_session_includes_tasks_summary(self, store, active_session):
        sid = active_session["id"]
        t1 = add_task(store, session_id=sid, title="a")
        add_task(store, session_id=sid, title="b")
        complete_task(store, task_id=t1["id"], **_COMMIT_KW)
        session = get_session(store, session_id=sid)
        assert session["tasks_summary"]["total"] == 2
        assert session["tasks_summary"]["completed"] == 1
        assert session["tasks_summary"]["pending"] == 1

    def test_resume_includes_open_tasks(self, store, active_session):
        sid = active_session["id"]
        add_task(store, session_id=sid, title="implementar X")
        add_task(store, session_id=sid, title="testar Y")
        result = resume_session(store, session_id=sid)
        assert len(result["open_tasks"]) == 2
        assert "implementar X" in result["resume_hint"]


# ────────────────────────────────────────────────────────────────────────────── #
# Service dependencies                                                        #
# ────────────────────────────────────────────────────────────────────────────── #


class TestAddServiceDependency:
    def test_links_service(self, store, active_session):
        sid = active_session["id"]
        result = add_service_dependency(
            store,
            session_id=sid,
            service="postgres",
            role="database",
            notes="instância dev",
        )
        assert result["service"] == "postgres"
        assert result["role"] == "database"
        assert result["notes"] == "instância dev"
        assert result["session_id"] == sid

    def test_duplicate_service_returns_error(self, store, active_session):
        sid = active_session["id"]
        add_service_dependency(store, session_id=sid, service="redis")
        result = add_service_dependency(store, session_id=sid, service="redis")
        assert result["error"] == "duplicate"

    def test_missing_service_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = add_service_dependency(store, session_id=sid, service="")
        assert result["error"] == "ValidationError"

    def test_session_not_found(self, store):
        result = add_service_dependency(store, session_id="sess_nope", service="x")
        assert result["error"] == "not_found"


class TestListServiceDependencies:
    def test_lists_all(self, store, active_session):
        sid = active_session["id"]
        add_service_dependency(store, session_id=sid, service="postgres", role="database")
        add_service_dependency(store, session_id=sid, service="redis", role="cache")
        result = list_service_dependencies(store, session_id=sid)
        assert result["count"] == 2
        services = {d["service"] for d in result["service_dependencies"]}
        assert services == {"postgres", "redis"}

    def test_empty_list(self, store, active_session):
        sid = active_session["id"]
        result = list_service_dependencies(store, session_id=sid)
        assert result["count"] == 0

    def test_session_not_found(self, store):
        result = list_service_dependencies(store, session_id="sess_nope")
        assert result["error"] == "not_found"


class TestRemoveServiceDependency:
    def test_removes_existing(self, store, active_session):
        sid = active_session["id"]
        add_service_dependency(store, session_id=sid, service="redis")
        result = remove_service_dependency(store, session_id=sid, service="redis")
        assert result["removed"] is True
        listed = list_service_dependencies(store, session_id=sid)
        assert listed["count"] == 0

    def test_remove_nonexistent_returns_error(self, store, active_session):
        sid = active_session["id"]
        result = remove_service_dependency(store, session_id=sid, service="ghost")
        assert result["error"] == "not_found"


class TestSessionIncludesServiceDependencies:
    def test_get_session_includes_deps(self, store, active_session):
        sid = active_session["id"]
        add_service_dependency(store, session_id=sid, service="postgres", role="database")
        session = get_session(store, session_id=sid)
        assert len(session["service_dependencies"]) == 1
        assert session["service_dependencies"][0]["service"] == "postgres"


class TestResumeWarnsWhenRepoMissing:
    def test_warning_present_for_legacy_session(self, store):
        # Insere uma sessão direto no DB sem repo (simulando legado)
        with store._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sessions (id, name, title, objective, repo, branch,
                       status, started_at, last_updated_at)
                       VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s)""",
                    ("sess_legacy", "old-name", "Legacy", "obj antigo", "active", "2020-01-01", "2020-01-01"),
                )
        result = resume_session(store, session_id="sess_legacy")
        assert any("REPO_MISSING" in w for w in result["warnings"])
        assert "REPO_MISSING" in result["resume_hint"]

    def test_no_warning_for_session_with_repo(self, store, active_session):
        result = resume_session(store, session_id=active_session["id"])
        assert all("REPO_MISSING" not in w for w in result.get("warnings", []))
        assert result["service_dependencies"] == []


# ────────────────────────────────────────────────────────────────────────────── #
# Decisão humana em tasks                                                     #
# ────────────────────────────────────────────────────────────────────────────── #


class TestNeedsHumanDecision:
    def test_add_task_with_flag(self, store, active_session):
        sid = active_session["id"]
        task = add_task(
            store, session_id=sid, title="risky migration", needs_human_decision=True
        )
        assert task["needs_human_decision"] == 1
        assert task["decision"] is None

    def test_start_task_blocks_until_decision(self, store, active_session):
        sid = active_session["id"]
        task = add_task(
            store, session_id=sid, title="risky migration", needs_human_decision=True
        )
        result = start_task(store, task_id=task["id"])
        assert result["error"] == "human_decision_pending"

    def test_approve_go_unblocks_start(self, store, active_session):
        sid = active_session["id"]
        task = add_task(
            store, session_id=sid, title="risky migration", needs_human_decision=True
        )
        approval = approve_task(
            store,
            task_id=task["id"],
            decision="go",
            actor=_ACTOR_HUMAN,
            rationale="reviewed",
        )
        assert approval["decision"] == "go"
        assert approval["status"] == "pending"
        result = start_task(store, task_id=task["id"])
        assert result["status"] == "in_progress"

    def test_approve_no_go_cancels(self, store, active_session):
        sid = active_session["id"]
        task = add_task(
            store, session_id=sid, title="risky migration", needs_human_decision=True
        )
        approval = approve_task(
            store,
            task_id=task["id"],
            decision="no_go",
            actor=_ACTOR_HUMAN,
            rationale="too dangerous",
        )
        assert approval["status"] == "cancelled"
        assert approval["decision"] == "no_go"
        assert "too dangerous" in approval["result"]

    def test_no_go_requires_rationale(self, store, active_session):
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="x", needs_human_decision=True)
        result = approve_task(
            store, task_id=task["id"], decision="no_go", actor=_ACTOR_HUMAN
        )
        assert result["error"] == "ValidationError"

    def test_invalid_decision_returns_error(self, store, active_session):
        sid = active_session["id"]
        task = add_task(
            store, session_id=sid, title="x", needs_human_decision=True
        )
        result = approve_task(
            store, task_id=task["id"], decision="maybe", actor=_ACTOR_HUMAN
        )
        assert result["error"] == "ValidationError"

    def test_normal_task_unaffected(self, store, active_session):
        # task sem o flag deve passar normalmente
        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="normal")
        assert task["needs_human_decision"] == 0
        result = start_task(store, task_id=task["id"])
        assert result["status"] == "in_progress"

    def test_bulk_with_per_item_flag(self, store, active_session):
        sid = active_session["id"]
        result = add_task(
            store,
            session_id=sid,
            tasks=[
                {"title": "safe"},
                {"title": "risky", "needs_human_decision": True},
            ],
        )
        assert result["count"] == 2
        flags = [t["needs_human_decision"] for t in result["tasks"]]
        assert flags == [0, 1]


# ────────────────────────────────────────────────────────────────────────────── #
# Cross-repo suggestions                                                      #
# ────────────────────────────────────────────────────────────────────────────── #


class TestSubmitSuggestion:
    def test_creates_suggestion(self, store, active_session):
        result = submit_suggestion(
            store,
            source_repo="platform-dai",
            target_repo="platform-auth",
            title="Adicionar refresh token",
            description="Rotação de tokens é ponto fraco",
            kind="addition",
            priority="high",
            source_session_id=active_session["id"],
        )
        assert result["id"]
        assert result["status"] == "pending"
        assert result["target_repo"] == "platform-auth"
        assert result["needs_human_decision"] is True

    def test_invalid_kind_returns_error(self, store):
        result = submit_suggestion(
            store, source_repo="a", target_repo="b", title="t", kind="weird"
        )
        assert result["error"] == "ValidationError"

    def test_missing_required_returns_error(self, store):
        result = submit_suggestion(store, source_repo="", target_repo="b", title="t")
        assert result["error"] == "ValidationError"


class TestListSuggestions:
    def test_filters_by_target_repo(self, store):
        submit_suggestion(store, source_repo="x", target_repo="A", title="a1")
        submit_suggestion(store, source_repo="x", target_repo="B", title="b1")
        result = list_suggestions_tool(store, target_repo="A")
        assert result["count"] == 1
        assert result["suggestions"][0]["title"] == "a1"

    def test_filters_by_status(self, store):
        s = submit_suggestion(store, source_repo="x", target_repo="A", title="a1")
        reject_suggestion(store, suggestion_id=s["id"], actor=_ACTOR_HUMAN, reason="no")
        result = list_suggestions_tool(store, status="rejected")
        assert result["count"] == 1


class TestAcceptSuggestion:
    def test_creates_task_with_inherited_flag(self, store, active_session):
        s = submit_suggestion(
            store,
            source_repo="platform-dai",
            target_repo=active_session["repo"],
            title="Refactor auth lib",
            description="Detalhes...",
        )
        result = accept_suggestion(
            store,
            suggestion_id=s["id"],
            session_id=active_session["id"],
            actor=_ACTOR_HUMAN,
            rationale="approved by team",
        )
        assert result["suggestion"]["status"] == "accepted"
        assert result["task"]["title"] == "Refactor auth lib"
        assert result["task"]["needs_human_decision"] == 1
        assert "[suggestion #" in (result["task"]["description"] or "")

    def test_repo_mismatch_blocks(self, store, active_session):
        s = submit_suggestion(
            store,
            source_repo="other",
            target_repo="some-other-repo",
            title="x",
        )
        result = accept_suggestion(
            store,
            suggestion_id=s["id"],
            session_id=active_session["id"],
            actor=_ACTOR_HUMAN,
        )
        assert result["error"] == "ValidationError"

    def test_already_accepted_blocks(self, store, active_session):
        s = submit_suggestion(
            store, source_repo="x", target_repo=active_session["repo"], title="x"
        )
        accept_suggestion(
            store,
            suggestion_id=s["id"],
            session_id=active_session["id"],
            actor=_ACTOR_HUMAN,
        )
        again = accept_suggestion(
            store,
            suggestion_id=s["id"],
            session_id=active_session["id"],
            actor=_ACTOR_HUMAN,
        )
        assert again["error"] == "invalid_transition"


class TestRejectDeferSupersede:
    def test_reject_with_reason(self, store):
        s = submit_suggestion(store, source_repo="x", target_repo="y", title="t")
        result = reject_suggestion(
            store, suggestion_id=s["id"], actor=_ACTOR_HUMAN, reason="duplicada"
        )
        assert result["status"] == "rejected"
        assert result["response_reason"] == "duplicada"

    def test_reject_without_reason_blocks(self, store):
        s = submit_suggestion(store, source_repo="x", target_repo="y", title="t")
        result = reject_suggestion(
            store, suggestion_id=s["id"], actor=_ACTOR_HUMAN, reason=""
        )
        assert result["error"] == "ValidationError"

    def test_defer(self, store):
        s = submit_suggestion(store, source_repo="x", target_repo="y", title="t")
        result = defer_suggestion(
            store, suggestion_id=s["id"], actor=_ACTOR_HUMAN, reason="depois"
        )
        assert result["status"] == "deferred"

    def test_supersede_with_reference(self, store):
        s1 = submit_suggestion(store, source_repo="x", target_repo="y", title="old")
        s2 = submit_suggestion(store, source_repo="x", target_repo="y", title="new")
        result = supersede_suggestion(
            store,
            suggestion_id=s1["id"],
            actor=_ACTOR_AGENT,
            by_suggestion_id=s2["id"],
        )
        assert result["status"] == "superseded"
        assert result["superseded_by"] == s2["id"]


class TestStartSessionIncludesSuggestions:
    def test_pending_suggestions_in_payload(self, store):
        submit_suggestion(
            store, source_repo="x", target_repo="platform-target", title="s1"
        )
        submit_suggestion(
            store, source_repo="x", target_repo="platform-target", title="s2"
        )
        session = start_session(
            store,
            "develop",
            title="t",
            objective="o",
            repo="platform-target",
        )
        assert session["pending_suggestions"]["count"] == 2
        titles = [s["title"] for s in session["pending_suggestions"]["items"]]
        assert "s1" in titles and "s2" in titles


class TestGetSuggestion:
    def test_returns_full(self, store):
        s = submit_suggestion(store, source_repo="x", target_repo="y", title="t")
        result = get_suggestion_tool(store, suggestion_id=s["id"])
        assert result["id"] == s["id"]
        assert result["title"] == "t"

    def test_not_found(self, store):
        result = get_suggestion_tool(store, suggestion_id=99999)
        assert result["error"] == "not_found"


# ────────────────────────────────────────────────────────────────────────────── #
# Decisions audit                                                             #
# ────────────────────────────────────────────────────────────────────────────── #


class TestDecisionsAudit:
    def test_approve_records_decision(self, store, active_session):
        from src.tools.session_tool import list_decisions_tool

        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="x", needs_human_decision=True)
        approve_task(
            store,
            task_id=task["id"],
            decision="go",
            actor=_ACTOR_HUMAN,
            rationale="reviewed",
        )
        decisions = list_decisions_tool(
            store, target_type="task", target_id=str(task["id"])
        )
        assert decisions["count"] == 1
        d = decisions["decisions"][0]
        assert d["actor_type"] == "human"
        assert d["actor_id"] == "test@dataforall.tech"
        assert d["action"] == "approve_task"
        assert d["decision"] == "go"
        assert d["rationale"] == "reviewed"

    def test_cancel_records_decision(self, store, active_session):
        from src.tools.session_tool import list_decisions_tool

        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="x")
        cancel_task(
            store, task_id=task["id"], actor=_ACTOR_AGENT, reason="abandoned"
        )
        decisions = list_decisions_tool(store, action="cancel_task")
        assert decisions["count"] == 1
        assert decisions["decisions"][0]["actor_type"] == "agent"
        assert decisions["decisions"][0]["rationale"] == "abandoned"

    def test_reject_suggestion_records_decision(self, store):
        from src.tools.session_tool import list_decisions_tool

        s = submit_suggestion(store, source_repo="x", target_repo="y", title="t")
        reject_suggestion(
            store, suggestion_id=s["id"], actor=_ACTOR_HUMAN, reason="dup"
        )
        decisions = list_decisions_tool(store, target_type="suggestion")
        assert decisions["count"] == 1
        assert decisions["decisions"][0]["action"] == "reject_suggestion"

    def test_filter_by_actor(self, store, active_session):
        from src.tools.session_tool import list_decisions_tool

        sid = active_session["id"]
        t1 = add_task(store, session_id=sid, title="a")
        t2 = add_task(store, session_id=sid, title="b")
        cancel_task(store, task_id=t1["id"], actor=_ACTOR_HUMAN, reason="r")
        cancel_task(store, task_id=t2["id"], actor=_ACTOR_AGENT, reason="r")
        human_decisions = list_decisions_tool(
            store, actor_type="human", actor_id="test@dataforall.tech"
        )
        assert human_decisions["count"] == 1
        agent_decisions = list_decisions_tool(store, actor_type="agent")
        assert agent_decisions["count"] == 1

    def test_get_decision(self, store, active_session):
        from src.tools.session_tool import get_decision_tool, list_decisions_tool

        sid = active_session["id"]
        task = add_task(store, session_id=sid, title="x", needs_human_decision=True)
        approve_task(
            store,
            task_id=task["id"],
            decision="no_go",
            actor=_ACTOR_HUMAN,
            rationale="too risky",
        )
        decisions = list_decisions_tool(store, action="approve_task")
        d_id = decisions["decisions"][0]["id"]
        result = get_decision_tool(store, decision_id=d_id)
        assert result["decision"] == "no_go"
        assert result["rationale"] == "too risky"

    def test_decision_get_not_found(self, store):
        from src.tools.session_tool import get_decision_tool

        result = get_decision_tool(store, decision_id=99999)
        assert result["error"] == "not_found"

    def test_invalid_actor_type_blocks_audit_query(self, store):
        from src.tools.session_tool import list_decisions_tool

        result = list_decisions_tool(store, actor_type="alien")
        assert result["error"] == "ValidationError"
