"""Tools de Pull Request.

Tools: create_pr, get_pr, merge_pr, list_prs
"""

from __future__ import annotations

from ..knowledge.github_client import GitHubClient, GitHubClientError


def _error(tool: str, exc: Exception) -> dict:
    return {"error": type(exc).__name__, "tool": tool, "details": str(exc)}


def create_pr(
    client: GitHubClient,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str | None = None,
    labels: list[str] | None = None,
    reviewers: list[str] | None = None,
    draft: bool = False,
) -> dict:
    """Abre um Pull Request.

    Args:
        repo: Nome do repo.
        title: Título do PR.
        body: Corpo/descrição do PR (markdown).
        head: Branch de origem (feature/minha-feature).
        base: Branch de destino. Default: DEPLOY_DEFAULT_BASE_BRANCH (develop).
        labels: Lista de labels a aplicar.
        reviewers: Lista de logins de reviewers.
        draft: Criar como rascunho. Default: False.
    """
    try:
        if not all([repo, title, head]):
            return {
                "error": "ValidationError",
                "tool": "create_pr",
                "details": "repo, title e head são obrigatórios.",
            }
        base_branch = base or client._settings.default_base_branch
        return client.create_pr(
            repo=repo,
            title=title,
            body=body or "",
            head=head,
            base=base_branch,
            labels=labels,
            reviewers=reviewers,
            draft=draft,
        )
    except GitHubClientError as exc:
        return _error("create_pr", exc)


def get_pr(client: GitHubClient, repo: str, pr_number: int) -> dict:
    """Retorna detalhes e status de checks de um PR.

    Args:
        repo: Nome do repo.
        pr_number: Número do PR.
    """
    try:
        if not repo or not pr_number:
            return {
                "error": "ValidationError",
                "tool": "get_pr",
                "details": "repo e pr_number são obrigatórios.",
            }
        return client.get_pr(repo, pr_number)
    except GitHubClientError as exc:
        return _error("get_pr", exc)


def merge_pr(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    method: str = "squash",
    commit_title: str | None = None,
    commit_message: str | None = None,
) -> dict:
    """Faz merge de um PR.

    Args:
        repo: Nome do repo.
        pr_number: Número do PR.
        method: Estratégia de merge: squash | merge | rebase. Default: squash.
        commit_title: Título do commit de merge (override).
        commit_message: Mensagem do commit de merge (override).
    """
    try:
        if not repo or not pr_number:
            return {
                "error": "ValidationError",
                "tool": "merge_pr",
                "details": "repo e pr_number são obrigatórios.",
            }
        if method not in ("squash", "merge", "rebase"):
            return {
                "error": "ValidationError",
                "tool": "merge_pr",
                "details": f"method inválido: {method!r}. Use squash, merge ou rebase.",
            }
        return client.merge_pr(repo, pr_number, method, commit_title, commit_message)
    except GitHubClientError as exc:
        return _error("merge_pr", exc)


def list_prs(
    client: GitHubClient,
    repo: str,
    state: str = "open",
    base: str | None = None,
    author: str | None = None,
) -> dict:
    """Lista Pull Requests de um repositório.

    Args:
        repo: Nome do repo.
        state: open | closed | all. Default: open.
        base: Filtrar por branch de destino.
        author: Filtrar por login do autor.
    """
    try:
        if not repo:
            return {
                "error": "ValidationError",
                "tool": "list_prs",
                "details": "repo é obrigatório.",
            }
        if state not in ("open", "closed", "all"):
            return {
                "error": "ValidationError",
                "tool": "list_prs",
                "details": f"state inválido: {state!r}. Use open, closed ou all.",
            }
        prs = client.list_prs(repo, state=state, base=base, author=author)
        return {"prs": prs, "count": len(prs)}
    except GitHubClientError as exc:
        return _error("list_prs", exc)
