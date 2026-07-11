"""Tools de sessão em memória (sem banco): whoami, get_twin_context, context_status,
refresh_context. Exercitam apenas o SessionManager singleton — não tocam o store."""

from __future__ import annotations

from src.knowledge.session import SessionManager, UserSession
from src.tools import auth_tool
from src.tools.auth_tool import context_status, get_twin_context, refresh_context, whoami


def _session(tool_calls: int = 0, authenticated_at: str = "2024-01-01T00:00:00+00:00", **over) -> UserSession:
    kw = dict(
        token="tok",
        user_id="uid",
        name="Zoe",
        email="zoe@test.com",
        role="developer",
        scopes=["*"],
        environment="dev",
        authenticated_at=authenticated_at,
        context={"git": {}},  # não-vazio → get_twin_context não dispara coleta de git
        tool_calls=tool_calls,
    )
    kw.update(over)
    return UserSession(**kw)


# ── whoami ────────────────────────────────────────────────────────────────────
class TestWhoami:
    def test_no_session(self):
        assert whoami()["authenticated"] is False

    def test_after_set(self):
        SessionManager.set(_session(name="Dave"))
        result = whoami()
        assert result["authenticated"] is True
        assert result["name"] == "Dave"


# ── get_twin_context ──────────────────────────────────────────────────────────
class TestGetTwinContext:
    def test_no_session(self):
        assert get_twin_context()["authenticated"] is False

    def test_with_session(self):
        SessionManager.set(_session(environment="staging"))
        result = get_twin_context()
        assert result["authenticated"] is True
        assert result["user"]["environment"] == "staging"
        assert "credential_namespaces" in result

    def test_tenant_namespaces(self):
        SessionManager.set(_session(tenant_id="tenant_abc"))
        result = get_twin_context()
        assert result["user"]["tenant_id"] == "tenant_abc"
        assert "tenants.tenant_abc" in result["tenant_namespaces"]

    def test_no_tenant_gives_empty_namespaces(self):
        SessionManager.set(_session(tenant_id=None))
        result = get_twin_context()
        assert result["user"]["tenant_id"] is None
        assert result["tenant_namespaces"] == []


# ── context_status (recomendação de /compact) ─────────────────────────────────
class TestContextStatus:
    def test_no_session(self):
        assert context_status()["authenticated"] is False

    def test_ok_recommendation(self):
        SessionManager.set(_session(tool_calls=1))
        result = context_status()
        assert result["recommendation"] == "ok"
        assert result["tool_calls"] == 1

    def test_compact_soon(self):
        SessionManager.set(_session(tool_calls=90))
        assert context_status()["recommendation"] == "compact_soon"

    def test_compact_now(self):
        SessionManager.set(_session(tool_calls=200))
        assert context_status()["recommendation"] == "compact_now"


# ── refresh_context ───────────────────────────────────────────────────────────
class TestRefreshContext:
    def test_no_session(self):
        assert refresh_context()["success"] is False

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
