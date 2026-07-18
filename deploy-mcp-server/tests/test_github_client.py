"""Testes para GitHubClient: secrets/variables, ACR token/tags, e branches de erro.

httpx e PyGithub são mockados — nenhuma chamada de rede real acontece.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import GithubException
from github.GithubException import UnknownObjectException

from src.knowledge.github_client import GitHubClient, GitHubClientError

from .conftest import make_mock_repo


@pytest.fixture(autouse=True)
def clear_acr_cache():
    """Garante que o cache de token ACR (atributo de classe) não vaza entre testes."""
    GitHubClient._acr_cache.clear()
    yield
    GitHubClient._acr_cache.clear()


# ─────────────────────────────────────────────────────────────────────────── #
# _repo resolution                                                              #
# ─────────────────────────────────────────────────────────────────────────── #
class TestRepoResolution:
    def test_prefixes_org_when_no_owner(self, client, mock_github):
        client._repo("bare-name")
        mock_github.get_repo.assert_called_with("test-org/bare-name")

    def test_keeps_owner_when_present(self, client, mock_github):
        client._repo("acme/widget")
        mock_github.get_repo.assert_called_with("acme/widget")

    def test_unknown_repo_raises_client_error(self, client, mock_github):
        mock_github.get_repo.side_effect = UnknownObjectException(404, "nf")
        with pytest.raises(GitHubClientError, match="não encontrado"):
            client._repo("ghost")

    def test_github_exception_raises_client_error(self, client, mock_github):
        mock_github.get_repo.side_effect = GithubException(500, "boom")
        with pytest.raises(GitHubClientError):
            client._repo("x")


# ─────────────────────────────────────────────────────────────────────────── #
# get_acr_token (com cache)                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
class TestGetAcrToken:
    def test_fetches_and_caches_token(self, client, monkeypatch):
        fake_httpx = MagicMock()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"access_token": "acr-token-abc"}
        fake_httpx.post.return_value = fake_resp
        monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)

        token1 = client.get_acr_token("reg.azurecr.io", "user", "pass")
        assert token1 == "acr-token-abc"

        # Segunda chamada deve usar cache (sem novo POST)
        token2 = client.get_acr_token("reg.azurecr.io", "user", "pass")
        assert token2 == "acr-token-abc"
        assert fake_httpx.post.call_count == 1

    def test_expired_cache_refetches(self, client, monkeypatch):
        # Injeta token expirado no cache
        GitHubClient._acr_cache["reg.azurecr.io:user"] = ("old", 0.0)

        fake_httpx = MagicMock()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"access_token": "fresh-token"}
        fake_httpx.post.return_value = fake_resp
        monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)

        token = client.get_acr_token("reg.azurecr.io", "user", "pass")
        assert token == "fresh-token"
        fake_httpx.post.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────── #
# list_acr_tags                                                                 #
# ─────────────────────────────────────────────────────────────────────────── #
class TestListAcrTags:
    def test_returns_normalized_tags(self, client, monkeypatch):
        monkeypatch.setattr(client, "get_acr_token", lambda *a, **k: "tok")

        fake_httpx = MagicMock()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "tags": [
                {
                    "name": "v3.1",
                    "digest": "sha256:aaa",
                    "createdTime": "2026-01-01",
                    "lastUpdateTime": "2026-01-02",
                }
            ]
        }
        fake_httpx.get.return_value = fake_resp
        monkeypatch.setitem(__import__("sys").modules, "httpx", fake_httpx)

        tags = client.list_acr_tags("reg", "ns", "svc", "u", "p", limit=10)
        assert len(tags) == 1
        assert tags[0]["name"] == "v3.1"
        assert tags[0]["created_at"] == "2026-01-01"

    def test_error_wrapped_as_client_error(self, client, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(client, "get_acr_token", boom)
        with pytest.raises(GitHubClientError, match="Erro ao listar tags"):
            client.list_acr_tags("reg", "ns", "svc", "u", "p")
