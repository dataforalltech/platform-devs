"""Cobertura das tools de contexto: context_status, refresh_context e o
branch de carregamento de config-mcp em authenticate()."""

from __future__ import annotations

import pytest

from src.knowledge.session import SessionManager, UserSession
from src.tools import auth_tool
from src.tools.auth_tool import authenticate, context_status, refresh_context


@pytest.fixture(autouse=True)
def clear_session():
    SessionManager.clear()
    yield
    SessionManager.clear()


def _session(tool_calls=0, authenticated_at="2024-01-01T00:00:00+00:00"):
    return UserSession(
        token="tok",
        user_id="uid",
        name="Zoe",
        email="zoe@test.com",
        role="developer",
        scopes=["*"],
        environment="dev",
        authenticated_at=authenticated_at,
        context={},
        tool_calls=tool_calls,
    )


class TestContextStatus:
    def test_no_session(self):
        result = context_status()
        assert result["authenticated"] is False

    def test_ok_recommendation(self):
        SessionManager.set(_session(tool_calls=1))
        result = context_status()
        assert result["recommendation"] == "ok"
        assert result["tool_calls"] == 1

    def test_compact_soon(self):
        SessionManager.set(_session(tool_calls=90))
        result = context_status()
        assert result["recommendation"] == "compact_soon"

    def test_compact_now(self):
        SessionManager.set(_session(tool_calls=200))
        result = context_status()
        assert result["recommendation"] == "compact_now"


class TestRefreshContext:
    def test_no_session(self):
        result = refresh_context()
        assert result["success"] is False

    def test_with_session(self, monkeypatch):
        monkeypatch.setattr(
            auth_tool,
            "collect_environment_context",
            lambda force=False: {"git": {"branch": "feat/x"}},
        )
        SessionManager.set(_session())
        result = refresh_context()
        assert result["success"] is True
        assert result["context"]["git"]["branch"] == "feat/x"


class TestAuthenticateConfigBranch:
    def test_loads_critical_env_config(self, store, monkeypatch):
        """Quando ConfigClient está disponível, authenticate carrega vars críticas."""

        class _FakeClient:
            @classmethod
            def from_env(cls):
                return cls()

            def get_env_config(self, environment):
                return {
                    "JWT_SECRET": "s3cr3t",
                    "URL_API": "http://x",
                    "INTERNAL_API_TOKEN": "tok",
                    "IRRELEVANT": "ignore-me",
                }

        monkeypatch.setattr(auth_tool, "_has_config_client", True, raising=False)
        monkeypatch.setattr(auth_tool, "ConfigClient", _FakeClient, raising=False)

        reg = store.register(name="Env", email="env@test.com")
        result = authenticate(store, reg["token"])
        assert result["authenticated"] is True
        assert result["env_config_loaded"] is True
        # JWT_ + URL_ prefixes e INTERNAL_API_TOKEN exato → 3 críticas, IRRELEVANT fora
        assert result["env_vars_count"] == 3

    def test_config_client_failure_is_non_blocking(self, store, monkeypatch):
        class _BoomClient:
            @classmethod
            def from_env(cls):
                raise RuntimeError("config-mcp down")

        monkeypatch.setattr(auth_tool, "_has_config_client", True, raising=False)
        monkeypatch.setattr(auth_tool, "ConfigClient", _BoomClient, raising=False)

        reg = store.register(name="Env2", email="env2@test.com")
        result = authenticate(store, reg["token"])
        assert result["authenticated"] is True
        assert result["env_config_loaded"] is False
