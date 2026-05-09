"""Tools de operações Git/repositório.

Tools: list_repos, create_branch, list_branches, commit_files
"""

from __future__ import annotations

from ..knowledge.github_client import GitHubClient, GitHubClientError


def _error(tool: str, exc: Exception) -> dict:
    return {"error": type(exc).__name__, "tool": tool, "details": str(exc)}


def list_repos(
    client: GitHubClient,
    org: str | None = None,
    filter_name: str | None = None,
    include_archived: bool = False,
) -> dict:
    """Lista repositórios da organização.

    Args:
        org: Organização GitHub. Default: DEPLOY_GITHUB_ORG.
        filter_name: Filtro substring no nome (case-insensitive).
        include_archived: Inclui repos arquivados. Default: False.
    """
    try:
        repos = client.list_repos(
            org=org, filter_name=filter_name, include_archived=include_archived
        )
        return {"repos": repos, "count": len(repos)}
    except GitHubClientError as exc:
        return _error("list_repos", exc)


def create_branch(
    client: GitHubClient,
    repo: str,
    branch: str,
    from_ref: str = "develop",
) -> dict:
    """Cria uma branch a partir de um ref (branch, tag ou SHA).

    Args:
        repo: Nome do repo (owner/name ou só name — usa org padrão).
        branch: Nome da nova branch.
        from_ref: Branch/tag/SHA base. Default: develop.
    """
    try:
        if not repo or not branch:
            return {
                "error": "ValidationError",
                "tool": "create_branch",
                "details": "repo e branch são obrigatórios.",
            }
        return client.create_branch(repo, branch, from_ref)
    except GitHubClientError as exc:
        return _error("create_branch", exc)


def list_branches(
    client: GitHubClient,
    repo: str,
    filter_name: str | None = None,
) -> dict:
    """Lista branches de um repositório.

    Args:
        repo: Nome do repo.
        filter_name: Filtro substring no nome.
    """
    try:
        branches = client.list_branches(repo, filter_name=filter_name)
        return {"branches": branches, "count": len(branches)}
    except GitHubClientError as exc:
        return _error("list_branches", exc)


def commit_files(
    client: GitHubClient,
    repo: str,
    branch: str,
    message: str,
    files: list[dict],
    author_name: str | None = None,
    author_email: str | None = None,
) -> dict:
    """Cria ou atualiza arquivos em um commit.

    Para múltiplos arquivos usa Git Data API (1 commit atômico).
    Para 1 arquivo usa Contents API.

    Args:
        repo: Nome do repo.
        branch: Branch de destino.
        message: Mensagem do commit.
        files: Lista de {path, content} — path relativo ao root.
        author_name: Nome do autor (optional — usa author padrão do token).
        author_email: Email do autor (optional).
    """
    try:
        if not repo or not branch or not message:
            return {
                "error": "ValidationError",
                "tool": "commit_files",
                "details": "repo, branch e message são obrigatórios.",
            }
        if not files:
            return {
                "error": "ValidationError",
                "tool": "commit_files",
                "details": "files não pode ser vazio.",
            }
        for f in files:
            if "path" not in f or "content" not in f:
                return {
                    "error": "ValidationError",
                    "tool": "commit_files",
                    "details": "Cada item de files deve ter 'path' e 'content'.",
                }
        return client.commit_files(repo, branch, message, files, author_name, author_email)
    except GitHubClientError as exc:
        return _error("commit_files", exc)
