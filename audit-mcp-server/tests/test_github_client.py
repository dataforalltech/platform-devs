"""Testes herméticos para GitHubClient (httpx.AsyncClient mockado)."""

import base64

import pytest

from src.knowledge import github_client
from src.knowledge.github_client import GitHubClient


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Substitui httpx.AsyncClient: responde conforme uma fila de respostas.

    A fila ``responses`` é de classe e consumida em ordem (via ``pop(0)``),
    de modo que chamadas recursivas (que instanciam novos clients) continuam
    consumindo da mesma fila.
    """

    responses: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        return FakeAsyncClient.responses.pop(0)


@pytest.fixture(autouse=True)
def patch_httpx(monkeypatch):
    monkeypatch.setattr(github_client.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.responses = []
    yield


def test_init_with_token():
    """Token preenche o header Authorization."""
    client = GitHubClient(token="abc", org="myorg")
    assert client.headers["Authorization"] == "token abc"
    assert client.org == "myorg"


def test_init_without_token():
    """Sem token, headers ficam vazios."""
    client = GitHubClient()
    assert client.headers == {}


async def test_get_repo_content_success():
    """Conteúdo base64 é decodificado."""
    raw = b"hello world"
    encoded = base64.b64encode(raw).decode()
    FakeAsyncClient.responses = [FakeResponse(200, {"content": encoded})]
    client = GitHubClient(token="t")
    content = await client.get_repo_content("repo", "README.md")
    assert content == raw


async def test_get_repo_content_404():
    """404 retorna None."""
    FakeAsyncClient.responses = [FakeResponse(404, {})]
    client = GitHubClient()
    assert await client.get_repo_content("repo", "missing") is None


async def test_get_repo_content_other_status():
    """Status != 200 retorna None."""
    FakeAsyncClient.responses = [FakeResponse(500, {})]
    client = GitHubClient()
    assert await client.get_repo_content("repo", "x") is None


async def test_get_repo_content_no_content_field():
    """Resposta 200 sem campo content retorna None."""
    FakeAsyncClient.responses = [FakeResponse(200, {"foo": "bar"})]
    client = GitHubClient()
    assert await client.get_repo_content("repo", "x") is None


async def test_list_repo_files_flat():
    """Lista arquivos de um diretório (sem recursão)."""
    FakeAsyncClient.responses = [
        FakeResponse(
            200,
            [
                {"type": "file", "path": "a.py"},
                {"type": "dir", "path": "sub"},
                {"type": "file", "path": "b.py"},
            ],
        )
    ]
    client = GitHubClient()
    files = await client.list_repo_files("repo")
    assert files == ["a.py", "b.py"]


async def test_list_repo_files_recursive():
    """Diretórios são percorridos quando recursive=True."""
    FakeAsyncClient.responses = [
        FakeResponse(200, [{"type": "dir", "path": "sub"}]),
        FakeResponse(200, [{"type": "file", "path": "sub/c.py"}]),
    ]
    client = GitHubClient()
    files = await client.list_repo_files("repo", recursive=True)
    assert files == ["sub/c.py"]


async def test_list_repo_files_non_200():
    """Status != 200 retorna lista vazia."""
    FakeAsyncClient.responses = [FakeResponse(404, [])]
    client = GitHubClient()
    assert await client.list_repo_files("repo") == []


async def test_list_repo_files_not_a_list():
    """Resposta que não é lista retorna []."""
    FakeAsyncClient.responses = [FakeResponse(200, {"message": "not found"})]
    client = GitHubClient()
    assert await client.list_repo_files("repo") == []


async def test_file_exists_true():
    """file_exists True quando get_repo_content retorna conteúdo."""
    encoded = base64.b64encode(b"x").decode()
    FakeAsyncClient.responses = [FakeResponse(200, {"content": encoded})]
    client = GitHubClient()
    assert await client.file_exists("repo", "x") is True


async def test_file_exists_false():
    """file_exists False quando o arquivo não existe."""
    FakeAsyncClient.responses = [FakeResponse(404, {})]
    client = GitHubClient()
    assert await client.file_exists("repo", "x") is False


async def test_list_files_matching():
    """list_files_matching filtra por padrão fnmatch."""
    FakeAsyncClient.responses = [
        FakeResponse(
            200,
            [
                {"type": "file", "path": "a.py"},
                {"type": "file", "path": "b.txt"},
            ],
        )
    ]
    client = GitHubClient()
    matched = await client.list_files_matching("repo", "*.py")
    assert matched == ["a.py"]
