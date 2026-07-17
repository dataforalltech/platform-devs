"""Cliente GitHub para deploy-mcp-server.

Encapsula todas as chamadas à GitHub REST API via PyGithub.
Thread-safe: cada operação usa o mesmo Github() singleton mas PyGithub é thread-safe
para leituras; operações de escrita são coordenadas pela camada de tools.

Erros da API são convertidos em GitHubClientError (subclasse de RuntimeError)
com mensagem descritiva — a camada de tools converte para dict {"error": ...}.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from github import Github, GithubException, InputGitTreeElement
from github.GithubException import UnknownObjectException

from ..config.settings import DeploySettings

_log = logging.getLogger(__name__)


class GitHubClientError(RuntimeError):
    """Erro da GitHub API com mensagem já formatada para o usuário."""


class GitHubClient:
    # Cache de tokens ACR: {registry:username → (token, expiry_timestamp)}
    _acr_cache: dict[str, tuple[str, float]] = {}

    def __init__(self, settings: DeploySettings) -> None:
        self._gh = Github(settings.github_token)
        self._settings = settings

    # ── helpers ────────────────────────────────────────────────────────────── #

    def _repo(self, name: str):
        """Resolve 'name' (usa org padrão) ou 'owner/name'."""
        if "/" not in name:
            name = f"{self._settings.github_org}/{name}"
        try:
            return self._gh.get_repo(name)
        except UnknownObjectException:
            raise GitHubClientError(f"Repo '{name}' não encontrado ou sem acesso.") from None
        except GithubException as exc:
            raise GitHubClientError(f"GitHub API error ao acessar repo '{name}': {exc}") from exc

    # ── Repos ──────────────────────────────────────────────────────────────── #

    def list_repos(
        self,
        org: str | None = None,
        filter_name: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        org_name = org or self._settings.github_org
        try:
            org_obj = self._gh.get_organization(org_name)
            result = []
            for repo in org_obj.get_repos():
                if not include_archived and repo.archived:
                    continue
                if filter_name and filter_name.lower() not in repo.name.lower():
                    continue
                result.append(
                    {
                        "name": repo.name,
                        "full_name": repo.full_name,
                        "default_branch": repo.default_branch,
                        "visibility": "private" if repo.private else "public",
                        "archived": repo.archived,
                        "url": repo.html_url,
                    }
                )
            return result
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao listar repos de '{org_name}': {exc}") from exc

    # ── Branches ───────────────────────────────────────────────────────────── #

    def create_branch(self, repo: str, branch: str, from_ref: str) -> dict[str, Any]:
        r = self._repo(repo)
        try:
            # Tenta como branch primeiro, depois como SHA direto
            try:
                source_sha = r.get_branch(from_ref).commit.sha
            except GithubException:
                source_sha = r.get_commit(from_ref).sha

            r.create_git_ref(ref=f"refs/heads/{branch}", sha=source_sha)
            return {"branch": branch, "sha": source_sha, "repo": repo}
        except GithubException as exc:
            if exc.status == 422:
                raise GitHubClientError(f"Branch '{branch}' já existe em '{repo}'.") from exc
            raise GitHubClientError(f"Erro ao criar branch '{branch}': {exc}") from exc

    def list_branches(self, repo: str, filter_name: str | None = None) -> list[dict[str, Any]]:
        r = self._repo(repo)
        try:
            result = []
            for b in r.get_branches():
                if filter_name and filter_name.lower() not in b.name.lower():
                    continue
                result.append({"name": b.name, "sha": b.commit.sha, "protected": b.protected})
            return result
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao listar branches: {exc}") from exc

    # ── Commits ────────────────────────────────────────────────────────────── #

    def commit_files(
        self,
        repo: str,
        branch: str,
        message: str,
        files: list[dict[str, str]],
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> dict[str, Any]:
        """Cria um commit com um ou mais arquivos.

        Para 1 arquivo: usa Contents API (simples).
        Para N arquivos: usa Git Data API (blob → tree → commit) — tudo num único commit.
        """
        r = self._repo(repo)
        try:
            if len(files) == 1:
                return self._commit_single(r, branch, message, files[0])
            return self._commit_multi(r, branch, message, files, author_name, author_email)
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao criar commit em '{repo}/{branch}': {exc}") from exc

    def _commit_single(self, r, branch: str, message: str, f: dict) -> dict[str, Any]:
        path, content = f["path"], f["content"]
        try:
            existing = r.get_contents(path, ref=branch)
            result = r.update_file(path, message, content, existing.sha, branch=branch)  # type: ignore[union-attr]
        except UnknownObjectException:
            result = r.create_file(path, message, content, branch=branch)
        commit = result["commit"]
        return {"sha": commit.sha, "url": commit.html_url, "files": [path]}

    def _commit_multi(
        self,
        r,
        branch: str,
        message: str,
        files: list[dict],
        author_name: str | None,
        author_email: str | None,
    ) -> dict[str, Any]:
        from github import InputGitAuthor

        ref = r.get_git_ref(f"heads/{branch}")
        parent_commit = r.get_git_commit(ref.object.sha)
        base_tree = parent_commit.tree

        elements = []
        for f in files:
            blob = r.create_git_blob(f["content"], "utf-8")
            elements.append(
                InputGitTreeElement(
                    path=f["path"],
                    mode="100644",
                    type="blob",
                    sha=blob.sha,
                )
            )

        tree = r.create_git_tree(elements, base_tree)
        commit_kwargs: dict[str, Any] = {
            "message": message,
            "tree": tree,
            "parents": [parent_commit],
        }
        if author_name:
            commit_kwargs["author"] = InputGitAuthor(
                name=author_name,
                email=author_email or f"{author_name}@users.noreply.github.com",
            )

        commit = r.create_git_commit(**commit_kwargs)
        ref.edit(commit.sha)
        return {
            "sha": commit.sha,
            "url": commit.html_url,
            "files": [f["path"] for f in files],
        }

    # ── Pull Requests ──────────────────────────────────────────────────────── #

    def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        labels: list[str] | None = None,
        reviewers: list[str] | None = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        r = self._repo(repo)
        try:
            pr = r.create_pull(title=title, body=body, head=head, base=base, draft=draft)
            if labels:
                pr.set_labels(*labels)
            if reviewers:
                pr.create_review_request(reviewers=reviewers)
            return self._pr_dict(pr)
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao criar PR em '{repo}': {exc}") from exc

    def get_pr(self, repo: str, pr_number: int) -> dict[str, Any]:
        r = self._repo(repo)
        try:
            pr = r.get_pull(pr_number)
            d = self._pr_dict(pr)
            # Busca check runs do último commit do PR
            checks = []
            try:
                for commit in pr.get_commits().reversed:
                    for run in commit.get_check_runs():
                        checks.append(
                            {
                                "name": run.name,
                                "status": run.status,
                                "conclusion": run.conclusion,
                                "url": run.html_url,
                            }
                        )
                    break  # só o último commit
            except GithubException:
                pass  # checks não disponíveis — sem permissão checks:read
            d["checks"] = checks
            return d
        except UnknownObjectException:
            raise GitHubClientError(f"PR #{pr_number} não encontrado em '{repo}'.") from None
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao buscar PR #{pr_number}: {exc}") from exc

    def merge_pr(
        self,
        repo: str,
        pr_number: int,
        method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        r = self._repo(repo)
        try:
            pr = r.get_pull(pr_number)
            kwargs: dict[str, Any] = {"merge_method": method}
            if commit_title:
                kwargs["commit_title"] = commit_title
            if commit_message:
                kwargs["commit_message"] = commit_message
            result = pr.merge(**kwargs)
            return {"merged": result.merged, "sha": result.sha, "message": result.message}
        except UnknownObjectException:
            raise GitHubClientError(f"PR #{pr_number} não encontrado em '{repo}'.") from None
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao fazer merge do PR #{pr_number}: {exc}") from exc

    def list_prs(
        self,
        repo: str,
        state: str = "open",
        base: str | None = None,
        author: str | None = None,
    ) -> list[dict[str, Any]]:
        r = self._repo(repo)
        try:
            kwargs: dict[str, Any] = {"state": state}
            if base:
                kwargs["base"] = base
            result = []
            for pr in r.get_pulls(**kwargs):
                if author and pr.user.login != author:
                    continue
                result.append(self._pr_dict(pr))
            return result
        except GithubException as exc:
            raise GitHubClientError(f"Erro ao listar PRs de '{repo}': {exc}") from exc

    def _pr_dict(self, pr) -> dict[str, Any]:
        return {
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "url": pr.html_url,
            "head": pr.head.ref,
            "base": pr.base.ref,
            "head_sha": pr.head.sha,
            "mergeable": pr.mergeable,
            "mergeable_state": pr.mergeable_state,
            "draft": pr.draft,
        }

    # ── ACR (tags via API REST com httpx) ─────────────────────────────────── #

    def get_acr_token(self, registry: str, username: str, password: str) -> str:
        """Obtém token de acesso OAuth2 do ACR (com cache de 1h).

        Evita re-autenticação desnecessária ao ACR em chamadas consecutivas.
        """
        cache_key = f"{registry}:{username}"
        cached = self._acr_cache.get(cache_key)
        if cached is not None:
            token, expiry = cached
            if time.time() < expiry:
                return token

        import httpx

        resp = httpx.post(
            f"https://{registry}/oauth2/token",
            data={
                "grant_type": "password",
                "service": registry,
                "scope": "registry:catalog:*",
                "username": username,
                "password": password,
            },
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        # Cache por 1 hora (tokens ACR expiram em 3h, mas usamos 1h por segurança)
        self._acr_cache[cache_key] = (token, time.time() + 3600)
        return token

    def list_acr_tags(
        self,
        registry: str,
        namespace: str,
        service_name: str,
        username: str,
        password: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Lista as tags mais recentes de uma imagem no ACR."""
        import httpx

        try:
            token = self.get_acr_token(registry, username, password)
            repo_path = f"{namespace}/{service_name}"
            resp = httpx.get(
                f"https://{registry}/acr/v1/{repo_path}/_tags",
                params={"orderby": "timedesc", "n": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            resp.raise_for_status()
            tags = resp.json().get("tags", [])
            return [
                {
                    "name": t["name"],
                    "digest": t.get("digest", ""),
                    "created_at": t.get("createdTime", ""),
                    "last_update": t.get("lastUpdateTime", ""),
                }
                for t in tags
            ]
        except Exception as exc:
            raise GitHubClientError(
                f"Erro ao listar tags do ACR '{registry}/{namespace}/{service_name}': {exc}"
            ) from exc
