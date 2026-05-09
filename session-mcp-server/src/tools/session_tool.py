"""Ferramentas de gerenciamento de sessões Claude Code.

Esta camada é puramente de estado: cada sessão sugere um nome de branch
(`session/<name>`) e cada task carrega o `commit_sha` que o agente realizou
via deploy-mcp. Operações git em si NÃO são feitas aqui — o agente é o
orquestrador que chama deploy-mcp.create_branch/commit_files e devolve
os resultados (sha) ao session-mcp via complete_task / confirm_branch.
"""

from __future__ import annotations

import re
from typing import Any

from ..db.store import (
    ACTOR_TYPES,
    SUGGESTION_KINDS,
    SUGGESTION_PRIORITIES,
    SUGGESTION_STATUSES,
    TASK_STATUSES,
    SessionStore,
)

_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9._\-/]+")


def sanitize_branch(name: str) -> str:
    """Garante que o nome é um ref Git válido (subset do que o GitHub aceita)."""
    clean = _BRANCH_SAFE.sub("-", name).strip("-/")
    return (clean or "session")[:240]

_VALID_STATUSES = {"active", "paused", "completed"}
_VALID_ARTIFACT_TYPES = {
    "file_changed",
    "file_created",
    "file_deleted",
    "decision",
    "tool_call",
    "error",
    "note",
}
_VALID_TASK_STATUSES = set(TASK_STATUSES)
_VALID_SUGGESTION_STATUSES = set(SUGGESTION_STATUSES)
_VALID_SUGGESTION_KINDS = set(SUGGESTION_KINDS)
_VALID_SUGGESTION_PRIORITIES = set(SUGGESTION_PRIORITIES)
_VALID_ACTOR_TYPES = set(ACTOR_TYPES)


def _validate_actor(actor: dict[str, Any] | None) -> dict[str, Any] | str:
    """Valida um dict {type, id}. Retorna dict normalizado ou string com erro."""
    if not isinstance(actor, dict):
        return "actor é obrigatório — informe { type: 'human'|'agent'|'system', id: '...' }"
    a_type = actor.get("type")
    a_id = actor.get("id")
    if a_type not in _VALID_ACTOR_TYPES:
        return f"actor.type deve ser um de: {sorted(_VALID_ACTOR_TYPES)}"
    if not a_id or not isinstance(a_id, str):
        return "actor.id é obrigatório (string não vazia)"
    return {"type": a_type, "id": a_id}


def _record(
    store: SessionStore,
    *,
    actor: dict[str, str],
    action: str,
    target_type: str,
    target_id: str | int,
    decision: str | None = None,
    rationale: str | None = None,
    context: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> None:
    """Wrapper conveniente para gravar decisão (silencioso, não bloqueia o caller)."""
    store.record_decision(
        actor_type=actor["type"],
        actor_id=actor["id"],
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        decision=decision,
        rationale=rationale,
        context=context,
        session_id=session_id,
    )


def _session_branch_name(name: str | None) -> str:
    base = (name or "session").lower()
    return sanitize_branch(f"session/{base}")


def start_session(
    store: SessionStore,
    default_base_branch: str,
    *,
    title: str,
    objective: str,
    repo: str,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Registra uma nova sessão e devolve o `branch_name` sugerido + a próxima ação
    que o agente deve executar via deploy-mcp.

    O session-mcp NÃO cria a branch — apenas registra a convenção.
    O agente deve chamar `mcp__deploy-mcp__create_branch(repo, branch, from_ref)`
    em seguida.

    `repo` é o repositório DONO da sessão (obrigatório). Para serviços auxiliares,
    use add_service_dependency consultando o services-mcp.
    Cada task completada deve carregar um commit_sha (feito via deploy-mcp.commit_files)."""
    if not title or not objective:
        return {"error": "ValidationError", "details": "title e objective são obrigatórios"}
    if not repo:
        return {
            "error": "ValidationError",
            "details": (
                "repo é obrigatório — informe o repositório dono da sessão. "
                "Para serviços auxiliares, use add_service_dependency após consultar "
                "o services-mcp."
            ),
        }

    base = base_branch or default_base_branch
    session = store.create_session(title=title, objective=objective, repo=repo)
    branch_name = _session_branch_name(session.get("name"))
    store.set_session_branch(session_id=session["id"], branch=branch_name, base_branch=base)
    session["branch"] = branch_name
    session["base_branch"] = base
    session["next_action"] = {
        "tool": "mcp__deploy-mcp__create_branch",
        "args": {"repo": repo, "branch": branch_name, "from_ref": base},
        "rationale": (
            "Crie a branch da sessão antes de qualquer commit. "
            "Use confirm_branch_created após o sucesso."
        ),
    }
    # Sugestões pendentes para esse repo (cross-repo queue)
    pending = store.list_suggestions(target_repo=repo, status="pending", limit=10)
    session["pending_suggestions"] = {
        "count": store.count_pending_suggestions(repo),
        "items": pending[:5],
    }
    return session


def confirm_branch_created(
    store: SessionStore,
    *,
    session_id: str,
    sha: str | None = None,
) -> dict[str, Any]:
    """Confirma (apenas para auditoria) que a branch da sessão foi criada via
    deploy-mcp. Se sha for informado, é gravado num artifact da sessão."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    session = store.get_session(session_id)
    if not session:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    if not session.get("branch"):
        return {
            "error": "ValidationError",
            "details": "Sessão não tem branch sugerida; use update_session ou recrie.",
        }
    if sha:
        store.add_artifact(
            session_id=session_id,
            artifact_type="note",
            content=f"Branch '{session['branch']}' criada — sha base {sha}",
        )
    return {"confirmed": True, "session_id": session_id, "branch": session["branch"]}


def save_checkpoint(
    store: SessionStore,
    *,
    session_id: str,
    summary: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Salva um snapshot do progresso da sessão."""
    if not session_id or not summary:
        return {"error": "ValidationError", "details": "session_id e summary são obrigatórios"}
    if not store.get_session(session_id):
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return store.save_checkpoint(session_id=session_id, summary=summary, context=context)


def update_session(
    store: SessionStore,
    *,
    session_id: str,
    status: str | None = None,
    progress: str | None = None,
) -> dict[str, Any]:
    """Atualiza status e/ou progresso de uma sessão."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    if status and status not in _VALID_STATUSES:
        return {
            "error": "ValidationError",
            "details": f"status deve ser um de: {sorted(_VALID_STATUSES)}",
        }
    result = store.update_session(session_id=session_id, status=status, progress=progress)
    if not result:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return result


def add_artifact(
    store: SessionStore,
    *,
    session_id: str,
    artifact_type: str,
    content: str,
) -> dict[str, Any]:
    """Registra um artefato/evento relevante na sessão (arquivo alterado, decisão, etc.)."""
    if not session_id or not artifact_type or not content:
        return {
            "error": "ValidationError",
            "details": "session_id, artifact_type e content são obrigatórios",
        }
    if artifact_type not in _VALID_ARTIFACT_TYPES:
        return {
            "error": "ValidationError",
            "details": f"artifact_type deve ser um de: {sorted(_VALID_ARTIFACT_TYPES)}",
        }
    if not store.get_session(session_id):
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return store.add_artifact(session_id=session_id, artifact_type=artifact_type, content=content)


def list_sessions(
    store: SessionStore,
    *,
    status: str | None = None,
    repo: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Lista sessões recentes, opcionalmente filtradas por status ou repo."""
    if status and status not in _VALID_STATUSES:
        return {
            "error": "ValidationError",
            "details": f"status deve ser um de: {sorted(_VALID_STATUSES)}",
        }
    sessions = store.list_sessions(status=status, repo=repo, limit=min(limit, 100))
    return {"count": len(sessions), "sessions": sessions}


def get_session(
    store: SessionStore,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Retorna dados completos de uma sessão (com último checkpoint e contagem de artefatos)."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    result = store.get_session(session_id)
    if not result:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return result


def resume_session(
    store: SessionStore,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Retorna o contexto completo para retomar uma sessão: checkpoints, artefatos e hint de retomada."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    result = store.get_resume_context(session_id)
    if not result:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    # Reativa a sessão se estava pausada
    session = result["session"]
    if session.get("status") == "paused":
        store.update_session(session_id=session_id, status="active")
        result["session"]["status"] = "active"
    return result


def end_session(
    store: SessionStore,
    *,
    session_id: str,
    actor: dict[str, Any],
    rationale: str,
    final_summary: str | None = None,
) -> dict[str, Any]:
    """Encerra uma sessão. Falha se houver tarefas abertas (pending/in_progress).
    Requer actor + rationale (decisão crítica de governança)."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    if not rationale:
        return {
            "error": "ValidationError",
            "details": "rationale é obrigatório em end_session (decisão crítica)",
        }
    result = store.end_session(session_id=session_id, final_summary=final_summary)
    if result is None:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    if isinstance(result, list):
        return {
            "error": "open_tasks",
            "details": (
                f"A sessão tem {len(result)} tarefa(s) aberta(s). "
                "Conclua, falhe ou cancele cada uma antes de encerrar."
            ),
            "open_tasks": result,
        }
    _record(
        store,
        actor=actor_v,
        action="end_session",
        target_type="session",
        target_id=session_id,
        decision="end",
        rationale=rationale,
        context={"final_summary": final_summary} if final_summary else None,
        session_id=session_id,
    )
    return result


# ── Tasks ────────────────────────────────────────────────────────────────── #


def add_task(
    store: SessionStore,
    *,
    session_id: str,
    title: str | None = None,
    description: str | None = None,
    needs_human_decision: bool = False,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cria uma tarefa (`title`) ou várias (`tasks=[{title, description?, needs_human_decision?}, ...]`).

    `needs_human_decision=True` marca a task como pendente de decisão humana — start_task
    vai bloquear até approve_task ser chamado com decision='go'."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    if tasks is not None:
        if not isinstance(tasks, list) or not tasks:
            return {
                "error": "ValidationError",
                "details": "tasks deve ser uma lista não vazia",
            }
        for idx, item in enumerate(tasks):
            if not isinstance(item, dict) or not item.get("title"):
                return {
                    "error": "ValidationError",
                    "details": f"tasks[{idx}] precisa ter campo 'title'",
                }
        created = store.create_tasks(session_id=session_id, tasks=tasks)
        if created is None:
            return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
        return {"count": len(created), "tasks": created}
    if not title:
        return {
            "error": "ValidationError",
            "details": "informe 'title' ou 'tasks' com a lista de tarefas",
        }
    task = store.create_task(
        session_id=session_id,
        title=title,
        description=description,
        needs_human_decision=needs_human_decision,
    )
    if task is None:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return task


def _handle_transition(result: Any, task_id: int, allowed_from: tuple[str, ...]) -> dict[str, Any]:
    if result is None:
        return {"error": "not_found", "details": f"Tarefa '{task_id}' não encontrada"}
    if isinstance(result, str):
        return {
            "error": "invalid_transition",
            "details": (
                f"Transição não permitida: tarefa está em '{result}', "
                f"esperado um de {sorted(allowed_from)}."
            ),
            "current_status": result,
        }
    return result


def start_task(store: SessionStore, *, task_id: int) -> dict[str, Any]:
    """Marca a tarefa como `in_progress` (só funciona a partir de `pending`).
    Bloqueia se a task tem needs_human_decision=true e ainda não recebeu decision='go'."""
    if not task_id:
        return {"error": "ValidationError", "details": "task_id é obrigatório"}
    task = store.get_task(task_id)
    if not task:
        return {"error": "not_found", "details": f"Tarefa '{task_id}' não encontrada"}
    if task["needs_human_decision"] and task["decision"] != "go":
        return {
            "error": "human_decision_pending",
            "details": (
                "Task requer decisão humana antes de iniciar. "
                "Chame approve_task(task_id, decision='go'|'no_go', notes?) primeiro."
            ),
            "task_id": task_id,
        }
    return _handle_transition(store.start_task(task_id), task_id, ("pending",))


def approve_task(
    store: SessionStore,
    *,
    task_id: int,
    decision: str,
    actor: dict[str, Any],
    rationale: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Registra a decisão sobre uma task pendente.

    decision='go'    → marca decision='go'; start_task fica liberado. rationale opcional.
    decision='no_go' → cancela a task usando notes como reason. rationale obrigatório."""
    if not task_id:
        return {"error": "ValidationError", "details": "task_id é obrigatório"}
    if decision not in ("go", "no_go"):
        return {
            "error": "ValidationError",
            "details": "decision deve ser 'go' ou 'no_go'",
        }
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    if decision == "no_go" and not rationale:
        return {
            "error": "ValidationError",
            "details": "rationale é obrigatório quando decision='no_go' (decisão crítica)",
        }
    result = store.approve_task(task_id, decision=decision, notes=notes or rationale)
    if result is None:
        return {"error": "not_found", "details": f"Tarefa '{task_id}' não encontrada"}
    if isinstance(result, str):
        return {
            "error": "invalid_transition",
            "details": (
                f"Decisão só é aceita para tasks pending; status atual: '{result}'."
            ),
            "current_status": result,
        }
    _record(
        store,
        actor=actor_v,
        action="approve_task",
        target_type="task",
        target_id=task_id,
        decision=decision,
        rationale=rationale or notes,
        session_id=result.get("session_id"),
    )
    return result


def complete_task(
    store: SessionStore,
    *,
    task_id: int,
    commit_sha: str,
    commit_message: str,
    result: str | None = None,
) -> dict[str, Any]:
    """Conclui a tarefa registrando o commit que o agente já fez via deploy-mcp.

    O commit em si NÃO é feito aqui — antes de chamar essa tool, o agente deve:
      1. Editar os arquivos.
      2. Chamar mcp__deploy-mcp__commit_files(repo, branch, message, files) e obter o sha.
      3. Chamar complete_task(task_id, commit_sha=sha, commit_message=message).

    Para tarefas que não geram código (investigar, decidir), use cancel_task com motivo."""
    if not task_id:
        return {"error": "ValidationError", "details": "task_id é obrigatório"}
    if not commit_sha:
        return {
            "error": "ValidationError",
            "details": (
                "commit_sha é obrigatório — faça o commit via "
                "mcp__deploy-mcp__commit_files e passe o sha aqui. "
                "Para tarefas sem código use cancel_task."
            ),
        }
    if not commit_message:
        return {"error": "ValidationError", "details": "commit_message é obrigatório"}

    transition = store.complete_task(
        task_id,
        result=result,
        commit_sha=commit_sha,
        commit_message=commit_message,
    )
    return _handle_transition(transition, task_id, ("pending", "in_progress"))


def fail_task(
    store: SessionStore,
    *,
    task_id: int,
    actor: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Marca a tarefa como `failed` registrando o motivo. reason vira rationale na audit."""
    if not task_id:
        return {"error": "ValidationError", "details": "task_id é obrigatório"}
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    if not reason:
        return {"error": "ValidationError", "details": "reason é obrigatório"}
    payload = _handle_transition(
        store.fail_task(task_id, reason=reason),
        task_id,
        ("pending", "in_progress"),
    )
    if isinstance(payload, dict) and "error" not in payload:
        _record(
            store,
            actor=actor_v,
            action="fail_task",
            target_type="task",
            target_id=task_id,
            decision="fail",
            rationale=reason,
            session_id=payload.get("session_id"),
        )
    return payload


def cancel_task(
    store: SessionStore,
    *,
    task_id: int,
    actor: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Cancela a tarefa (de `pending` ou `in_progress`). reason obrigatório (governança)."""
    if not task_id:
        return {"error": "ValidationError", "details": "task_id é obrigatório"}
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    if not reason:
        return {"error": "ValidationError", "details": "reason é obrigatório (decisão crítica)"}
    payload = _handle_transition(
        store.cancel_task(task_id, reason=reason),
        task_id,
        ("pending", "in_progress"),
    )
    if isinstance(payload, dict) and "error" not in payload:
        _record(
            store,
            actor=actor_v,
            action="cancel_task",
            target_type="task",
            target_id=task_id,
            decision="cancel",
            rationale=reason,
            session_id=payload.get("session_id"),
        )
    return payload


def list_tasks(
    store: SessionStore,
    *,
    session_id: str,
    status: str | None = None,
) -> dict[str, Any]:
    """Lista as tarefas de uma sessão, opcionalmente filtrando por status."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    if status and status not in _VALID_TASK_STATUSES:
        return {
            "error": "ValidationError",
            "details": f"status deve ser um de: {sorted(_VALID_TASK_STATUSES)}",
        }
    tasks = store.list_tasks(session_id=session_id, status=status)
    if tasks is None:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return {"count": len(tasks), "tasks": tasks}


def get_task(store: SessionStore, *, task_id: int) -> dict[str, Any]:
    """Retorna os dados de uma tarefa pelo ID."""
    if not task_id:
        return {"error": "ValidationError", "details": "task_id é obrigatório"}
    task = store.get_task(task_id)
    if not task:
        return {"error": "not_found", "details": f"Tarefa '{task_id}' não encontrada"}
    return task


# ── Service dependencies ────────────────────────────────────────────────────── #


def add_service_dependency(
    store: SessionStore,
    *,
    session_id: str,
    service: str,
    role: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Vincula um serviço auxiliar (do services-mcp) à sessão.
    O agente deve resolver o nome canônico via services-mcp antes de chamar."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    if not service:
        return {
            "error": "ValidationError",
            "details": (
                "service é obrigatório — informe o nome canônico do serviço "
                "(consulte o services-mcp para descobrir os disponíveis)"
            ),
        }
    result = store.add_service_dependency(
        session_id=session_id, service=service, role=role, notes=notes
    )
    if result is None:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    if result == "duplicate":
        return {
            "error": "duplicate",
            "details": f"Serviço '{service}' já está vinculado à sessão '{session_id}'",
        }
    return result


def list_service_dependencies(
    store: SessionStore,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Lista os serviços auxiliares vinculados à sessão."""
    if not session_id:
        return {"error": "ValidationError", "details": "session_id é obrigatório"}
    deps = store.list_service_dependencies(session_id=session_id)
    if deps is None:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    return {"count": len(deps), "service_dependencies": deps}


def remove_service_dependency(
    store: SessionStore,
    *,
    session_id: str,
    service: str,
) -> dict[str, Any]:
    """Remove o vínculo de um serviço auxiliar com a sessão."""
    if not session_id or not service:
        return {
            "error": "ValidationError",
            "details": "session_id e service são obrigatórios",
        }
    result = store.remove_service_dependency(session_id=session_id, service=service)
    if result is None:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    if result is False:
        return {
            "error": "not_found",
            "details": f"Serviço '{service}' não estava vinculado à sessão '{session_id}'",
        }
    return {"removed": True, "session_id": session_id, "service": service}


# ── Cross-repo suggestions ────────────────────────────────────────────────────── #


def submit_suggestion(
    store: SessionStore,
    *,
    source_repo: str,
    target_repo: str,
    title: str,
    description: str | None = None,
    kind: str | None = None,
    priority: str | None = None,
    needs_human_decision: bool = True,
    source_session_id: str | None = None,
) -> dict[str, Any]:
    """Cria uma sugestão de melhoria/correção/adição que `source_repo` faz para `target_repo`.
    Quando aceita via accept_suggestion, vira uma task no repo target — propagando o
    flag needs_human_decision (default True para sugestões cross-repo)."""
    if not source_repo or not target_repo or not title:
        return {
            "error": "ValidationError",
            "details": "source_repo, target_repo e title são obrigatórios",
        }
    if kind and kind not in _VALID_SUGGESTION_KINDS:
        return {
            "error": "ValidationError",
            "details": f"kind deve ser um de: {sorted(_VALID_SUGGESTION_KINDS)}",
        }
    if priority and priority not in _VALID_SUGGESTION_PRIORITIES:
        return {
            "error": "ValidationError",
            "details": f"priority deve ser um de: {sorted(_VALID_SUGGESTION_PRIORITIES)}",
        }
    suggestion = store.create_suggestion(
        source_repo=source_repo,
        target_repo=target_repo,
        title=title,
        description=description,
        kind=kind,
        priority=priority,
        source_session_id=source_session_id,
    )
    # Anota inheritance via response_reason ainda não — armazenamos como decision_notes
    # na task quando accept ocorrer. needs_human_decision é propagado em memory na função
    # accept_suggestion abaixo.
    suggestion["needs_human_decision"] = needs_human_decision
    return suggestion


def list_suggestions_tool(
    store: SessionStore,
    *,
    target_repo: str | None = None,
    source_repo: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Lista sugestões com filtros opcionais por target_repo, source_repo, status."""
    if status and status not in _VALID_SUGGESTION_STATUSES:
        return {
            "error": "ValidationError",
            "details": f"status deve ser um de: {sorted(_VALID_SUGGESTION_STATUSES)}",
        }
    items = store.list_suggestions(
        target_repo=target_repo, source_repo=source_repo, status=status, limit=min(limit, 200)
    )
    return {"count": len(items), "suggestions": items}


def get_suggestion_tool(
    store: SessionStore,
    *,
    suggestion_id: int,
) -> dict[str, Any]:
    if not suggestion_id:
        return {"error": "ValidationError", "details": "suggestion_id é obrigatório"}
    item = store.get_suggestion(suggestion_id)
    if not item:
        return {"error": "not_found", "details": f"Sugestão '{suggestion_id}' não encontrada"}
    return item


def accept_suggestion(
    store: SessionStore,
    *,
    suggestion_id: int,
    session_id: str,
    actor: dict[str, Any],
    rationale: str | None = None,
    needs_human_decision: bool | None = None,
) -> dict[str, Any]:
    """Aceita a sugestão e cria uma task na sessão informada."""
    if not suggestion_id or not session_id:
        return {
            "error": "ValidationError",
            "details": "suggestion_id e session_id são obrigatórios",
        }
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    suggestion = store.get_suggestion(suggestion_id)
    if not suggestion:
        return {"error": "not_found", "details": f"Sugestão '{suggestion_id}' não encontrada"}
    if suggestion["status"] != "pending":
        return {
            "error": "invalid_transition",
            "details": f"Sugestão está em '{suggestion['status']}' — só pending pode ser aceita.",
            "current_status": suggestion["status"],
        }
    session = store.get_session(session_id)
    if not session:
        return {"error": "not_found", "details": f"Sessão '{session_id}' não encontrada"}
    if session.get("repo") and session["repo"] != suggestion["target_repo"]:
        return {
            "error": "ValidationError",
            "details": (
                f"Sessão '{session_id}' é do repo '{session['repo']}' mas a sugestão "
                f"é para '{suggestion['target_repo']}'."
            ),
        }
    needs_decision = (
        needs_human_decision if needs_human_decision is not None else True
    )
    description = suggestion.get("description") or ""
    if suggestion.get("source_repo"):
        prefix = f"[suggestion #{suggestion_id} from {suggestion['source_repo']}]"
        description = f"{prefix}\n\n{description}".strip()
    task = store.create_task(
        session_id=session_id,
        title=suggestion["title"],
        description=description,
        needs_human_decision=needs_decision,
    )
    transitioned = store.transition_suggestion(
        suggestion_id,
        new_status="accepted",
        accepted_session_id=session_id,
        accepted_task_id=task["id"],
    )
    _record(
        store,
        actor=actor_v,
        action="accept_suggestion",
        target_type="suggestion",
        target_id=suggestion_id,
        decision="accept",
        rationale=rationale,
        context={"task_id": task["id"]},
        session_id=session_id,
    )
    return {"suggestion": transitioned, "task": task}


def reject_suggestion(
    store: SessionStore,
    *,
    suggestion_id: int,
    actor: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    if not suggestion_id or not reason:
        return {"error": "ValidationError", "details": "suggestion_id e reason são obrigatórios"}
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    result = store.transition_suggestion(
        suggestion_id, new_status="rejected", response_reason=reason
    )
    payload = _handle_suggestion_transition(result, suggestion_id)
    if isinstance(payload, dict) and "error" not in payload:
        _record(
            store,
            actor=actor_v,
            action="reject_suggestion",
            target_type="suggestion",
            target_id=suggestion_id,
            decision="reject",
            rationale=reason,
        )
    return payload


def defer_suggestion(
    store: SessionStore,
    *,
    suggestion_id: int,
    actor: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    if not suggestion_id:
        return {"error": "ValidationError", "details": "suggestion_id é obrigatório"}
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    result = store.transition_suggestion(
        suggestion_id, new_status="deferred", response_reason=reason
    )
    payload = _handle_suggestion_transition(result, suggestion_id)
    if isinstance(payload, dict) and "error" not in payload:
        _record(
            store,
            actor=actor_v,
            action="defer_suggestion",
            target_type="suggestion",
            target_id=suggestion_id,
            decision="defer",
            rationale=reason,
        )
    return payload


def supersede_suggestion(
    store: SessionStore,
    *,
    suggestion_id: int,
    actor: dict[str, Any],
    by_suggestion_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if not suggestion_id:
        return {"error": "ValidationError", "details": "suggestion_id é obrigatório"}
    actor_v = _validate_actor(actor)
    if isinstance(actor_v, str):
        return {"error": "ValidationError", "details": actor_v}
    result = store.transition_suggestion(
        suggestion_id,
        new_status="superseded",
        response_reason=reason,
        superseded_by=by_suggestion_id,
    )
    payload = _handle_suggestion_transition(result, suggestion_id)
    if isinstance(payload, dict) and "error" not in payload:
        _record(
            store,
            actor=actor_v,
            action="supersede_suggestion",
            target_type="suggestion",
            target_id=suggestion_id,
            decision="supersede",
            rationale=reason,
            context={"by_suggestion_id": by_suggestion_id} if by_suggestion_id else None,
        )
    return payload


def _handle_suggestion_transition(result: Any, suggestion_id: int) -> dict[str, Any]:
    if result is None:
        return {"error": "not_found", "details": f"Sugestão '{suggestion_id}' não encontrada"}
    if isinstance(result, str):
        return {
            "error": "invalid_transition",
            "details": f"Sugestão está em '{result}' — só pending aceita transição.",
            "current_status": result,
        }
    return result


# ── Decisions audit ───────────────────────────────────────────────────────────────── #


def list_decisions_tool(
    store: SessionStore,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Lista o audit trail de decisões com filtros."""
    if actor_type and actor_type not in _VALID_ACTOR_TYPES:
        return {
            "error": "ValidationError",
            "details": f"actor_type deve ser um de: {sorted(_VALID_ACTOR_TYPES)}",
        }
    items = store.list_decisions(
        target_type=target_type,
        target_id=target_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        session_id=session_id,
        limit=min(limit, 500),
    )
    return {"count": len(items), "decisions": items}


def get_decision_tool(
    store: SessionStore,
    *,
    decision_id: int,
) -> dict[str, Any]:
    if not decision_id:
        return {"error": "ValidationError", "details": "decision_id é obrigatório"}
    item = store.get_decision(decision_id)
    if not item:
        return {"error": "not_found", "details": f"Decisão '{decision_id}' não encontrada"}
    return item
