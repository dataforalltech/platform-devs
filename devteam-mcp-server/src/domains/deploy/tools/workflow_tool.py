"""Tools de GitHub Actions Workflows.

Tools: trigger_workflow, list_workflow_runs, get_workflow_run, cancel_workflow_run
"""

from __future__ import annotations

from ..knowledge.github_client import GitHubClient, GitHubClientError


def _error(tool: str, exc: Exception) -> dict:
    return {"error": type(exc).__name__, "tool": tool, "details": str(exc)}


def trigger_workflow(
    client: GitHubClient,
    repo: str,
    workflow_id: str,
    ref: str,
    inputs: dict[str, str] | None = None,
) -> dict:
    """Dispara um workflow via workflow_dispatch.

    Args:
        repo: Nome do repo.
        workflow_id: Nome do arquivo do workflow (ex: deploy.yml) ou ID numérico.
        ref: Branch, tag ou SHA para disparar o workflow.
        inputs: Inputs do workflow_dispatch (chave → valor string).

    Nota: A API do GitHub não retorna o run_id na resposta do dispatch.
          Use list_workflow_runs logo após para localizar o run criado.
    """
    try:
        if not all([repo, workflow_id, ref]):
            return {
                "error": "ValidationError",
                "tool": "trigger_workflow",
                "details": "repo, workflow_id e ref são obrigatórios.",
            }
        return client.trigger_workflow(repo, workflow_id, ref, inputs)
    except GitHubClientError as exc:
        return _error("trigger_workflow", exc)


def list_workflow_runs(
    client: GitHubClient,
    repo: str,
    workflow_id: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> dict:
    """Lista runs recentes de workflows.

    Args:
        repo: Nome do repo.
        workflow_id: Filtrar por workflow (arquivo ou ID). Default: todos.
        branch: Filtrar por branch.
        status: Filtrar por status: queued | in_progress | completed | success | failure | cancelled.
        limit: Máximo de runs a retornar. Default: 10.
    """
    try:
        if not repo:
            return {
                "error": "ValidationError",
                "tool": "list_workflow_runs",
                "details": "repo é obrigatório.",
            }
        runs = client.list_workflow_runs(
            repo,
            workflow_id=workflow_id,
            branch=branch,
            status=status,
            limit=min(limit, 50),
        )
        return {"runs": runs, "count": len(runs)}
    except GitHubClientError as exc:
        return _error("list_workflow_runs", exc)


def get_workflow_run(client: GitHubClient, repo: str, run_id: int) -> dict:
    """Retorna status detalhado de um workflow run.

    Args:
        repo: Nome do repo.
        run_id: ID numérico do run (retornado por list_workflow_runs).
    """
    try:
        if not repo or not run_id:
            return {
                "error": "ValidationError",
                "tool": "get_workflow_run",
                "details": "repo e run_id são obrigatórios.",
            }
        return client.get_workflow_run(repo, run_id)
    except GitHubClientError as exc:
        return _error("get_workflow_run", exc)


def cancel_workflow_run(client: GitHubClient, repo: str, run_id: int) -> dict:
    """Cancela um workflow run em andamento.

    Args:
        repo: Nome do repo.
        run_id: ID numérico do run.
    """
    try:
        if not repo or not run_id:
            return {
                "error": "ValidationError",
                "tool": "cancel_workflow_run",
                "details": "repo e run_id são obrigatórios.",
            }
        return client.cancel_workflow_run(repo, run_id)
    except GitHubClientError as exc:
        return _error("cancel_workflow_run", exc)
