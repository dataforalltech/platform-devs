import base64
import httpx
from typing import Any


class GitHubClient:
    """GitHub API client para download e inspeção de repos remotos."""

    def __init__(self, token: str = "", org: str = "dataforalltech"):
        self.token = token
        self.org = org
        self.base_url = "https://api.github.com"
        self.headers = {}
        if token:
            self.headers["Authorization"] = f"token {token}"

    async def get_repo_content(self, repo: str, path: str, ref: str = "main") -> bytes | None:
        """Lê conteúdo de um arquivo no repo."""
        url = f"{self.base_url}/repos/{self.org}/{repo}/contents/{path}"
        params = {"ref": ref}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, headers=self.headers, params=params)
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    return None

                data = resp.json()
                if "content" not in data:
                    return None

                return base64.b64decode(data["content"])
            except Exception:
                return None

    async def list_repo_files(
        self, repo: str, path: str = "", ref: str = "main", recursive: bool = False
    ) -> list[str]:
        """Lista arquivos em um diretório do repo."""
        files = []
        url = f"{self.base_url}/repos/{self.org}/{repo}/contents/{path}"
        params = {"ref": ref}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, headers=self.headers, params=params)
                if resp.status_code != 200:
                    return []

                data = resp.json()
                if not isinstance(data, list):
                    return []

                for item in data:
                    if item["type"] == "file":
                        files.append(item["path"])
                    elif item["type"] == "dir" and recursive:
                        sub_files = await self.list_repo_files(repo, item["path"], ref, recursive)
                        files.extend(sub_files)

                return files
            except Exception:
                return []

    async def file_exists(self, repo: str, path: str, ref: str = "main") -> bool:
        """Verifica se um arquivo existe."""
        content = await self.get_repo_content(repo, path, ref)
        return content is not None

    async def list_files_matching(
        self, repo: str, pattern: str, ref: str = "main"
    ) -> list[str]:
        """Lista arquivos que correspondem a um padrão (simples)."""
        import fnmatch

        all_files = await self.list_repo_files(repo, "", ref, recursive=True)
        return [f for f in all_files if fnmatch.fnmatch(f, pattern)]
