import os
from pathlib import Path


class RepoResolver:
    """Resolve repo path — local ou via GitHub API para remoto."""

    def __init__(self, github_token: str = "", github_org: str = "dataforalltech"):
        self.github_token = github_token
        self.github_org = github_org
        self._temp_dirs: dict[str, str] = {}

    def resolve(self, repo: str, repo_path: str | None = None, env: str = "dev") -> str | None:
        """
        Resolve path do repo.

        - Se repo_path fornecido e existe localmente: return repo_path
        - Se repo_path não fornecido e env != 'dev': retorna None (precisa GitHub
          API, não implementado nesta fase)
        - Se repo_path não fornecido e env == 'dev': tenta encontrar em /home/dev/repos
        """
        if repo_path:
            if Path(repo_path).exists():
                return repo_path
            return None

        if env == "dev":
            candidates = [
                os.environ.get("AUDIT_REPOS_ROOT", ""),
                os.environ.get("REPOS_ROOT", ""),
                "/repos",
                "/home/dev/repos",
            ]
            for root in candidates:
                if root:
                    p = Path(root) / repo
                    if p.exists():
                        return str(p)

        return None

    def cleanup(self) -> None:
        """Limpa diretórios temporários criados durante a auditoria."""
        for temp_dir in self._temp_dirs.values():
            if Path(temp_dir).exists():
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_dirs.clear()
