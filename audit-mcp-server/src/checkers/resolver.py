import os
import tempfile
from pathlib import Path
from typing import Any


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
        - Se repo_path não fornecido e env != 'dev': retorna None (precisa GitHub API, não implementado nesta fase)
        - Se repo_path não fornecido e env == 'dev': tenta encontrar em /home/dev/repos
        """
        if repo_path:
            if Path(repo_path).exists():
                return repo_path
            return None

        if env == "dev":
            local_path = f"/home/dev/repos/{repo}"
            if Path(local_path).exists():
                return local_path

        return None

    def cleanup(self) -> None:
        """Limpa diretórios temporários criados durante a auditoria."""
        for temp_dir in self._temp_dirs.values():
            if Path(temp_dir).exists():
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_dirs.clear()
