"""Tools de auth/admin contra o store canônico (MySQL real, §16 / FID-02).

authenticate carrega o perfil do token; as admin tools (register/revoke/rotate/list)
exigem o TWIN_ADMIN_TOKEN e delegam ao store tenant-scoped."""

from __future__ import annotations

import pytest

from src.knowledge.session import SessionManager
from src.tools import auth_tool
from src.tools.admin_tool import list_tokens, register_token, revoke_token, rotate_token
from src.tools.auth_tool import authenticate

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]

_ADMIN = "admin-secret-token-for-tests"


# ── authenticate ──────────────────────────────────────────────────────────────
class TestAuthenticate:
    async def test_valid_token(self, store_a):
        record = await store_a.register(name="Alice", email="alice@test.com")
        result = await authenticate(store_a, record["token"])
        assert result["authenticated"] is True
        assert result["name"] == "Alice"
        # authenticate é slim — sem contexto (coletado lazy em get_twin_context)
        assert "context" not in result

    async def test_invalid_token(self, store_a):
        result = await authenticate(store_a, "bad-token")
        assert result["authenticated"] is False
        assert "error" in result

    async def test_sets_session(self, store_a):
        record = await store_a.register(name="Bob", email="bob@test.com")
        await authenticate(store_a, record["token"])
        assert SessionManager.is_authenticated()
        assert SessionManager.get().name == "Bob"

    async def test_revoked_token_fails(self, store_a):
        record = await store_a.register(name="Carol", email="carol@test.com")
        await store_a.revoke(record["token"])
        result = await authenticate(store_a, record["token"])
        assert result["authenticated"] is False

    async def test_carries_tenant_id(self, store_a):
        record = await store_a.register(name="Tn", email="tn@test.com", tenant_id="tenant_abc")
        result = await authenticate(store_a, record["token"])
        assert result["tenant_id"] == "tenant_abc"


# ── authenticate + config-mcp branch ──────────────────────────────────────────
class TestAuthenticateConfigBranch:
    async def test_loads_critical_env_config(self, store_a, monkeypatch):
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

        reg = await store_a.register(name="Env", email="env@test.com")
        result = await authenticate(store_a, reg["token"])
        assert result["authenticated"] is True
        assert result["env_config_loaded"] is True
        # JWT_ + URL_ prefixes e INTERNAL_API_TOKEN exato → 3 críticas, IRRELEVANT fora
        assert result["env_vars_count"] == 3

    async def test_config_client_failure_is_non_blocking(self, store_a, monkeypatch):
        class _BoomClient:
            @classmethod
            def from_env(cls):
                raise RuntimeError("config-mcp down")

        monkeypatch.setattr(auth_tool, "_has_config_client", True, raising=False)
        monkeypatch.setattr(auth_tool, "ConfigClient", _BoomClient, raising=False)

        reg = await store_a.register(name="Env2", email="env2@test.com")
        result = await authenticate(store_a, reg["token"])
        assert result["authenticated"] is True
        assert result["env_config_loaded"] is False


# ── admin tools ───────────────────────────────────────────────────────────────
class TestAdminTools:
    async def test_register_requires_admin_token(self, store_a):
        result = await register_token(
            store_a,
            admin_token_configured=_ADMIN,
            admin_token="wrong",
            name="X",
            email="x@test.com",
        )
        assert result["error"] == "Unauthorized"

    async def test_register_not_configured(self, store_a):
        result = await register_token(
            store_a,
            admin_token_configured="",
            admin_token="anything",
            name="X",
            email="x@test.com",
        )
        assert result["error"] == "AdminNotConfigured"

    async def test_register_success(self, store_a):
        result = await register_token(
            store_a,
            admin_token_configured=_ADMIN,
            admin_token=_ADMIN,
            name="Frank",
            email="frank@test.com",
        )
        assert result["success"] is True
        assert result["token"]
        assert result["warning"]

    async def test_register_with_tenant_id(self, store_a):
        result = await register_token(
            store_a,
            admin_token_configured=_ADMIN,
            admin_token=_ADMIN,
            name="J",
            email="j@test.com",
            tenant_id="tenant_xyz99",
        )
        assert result["success"] is True
        assert result["tenant_id"] == "tenant_xyz99"
        auth = await authenticate(store_a, result["token"])
        assert auth["tenant_id"] == "tenant_xyz99"

    async def test_list_tokens(self, store_a):
        await store_a.register(name="G", email="g@test.com")
        result = await list_tokens(store_a, admin_token_configured=_ADMIN, admin_token=_ADMIN)
        assert result["count"] >= 1
        for t in result["tokens"]:
            assert "token" not in t

    async def test_revoke_via_admin(self, store_a):
        record = await store_a.register(name="H", email="h@test.com")
        result = await revoke_token(
            store_a,
            admin_token_configured=_ADMIN,
            admin_token=_ADMIN,
            identifier=record["token"],
        )
        assert result["success"] is True

    async def test_rotate_via_admin(self, store_a):
        record = await store_a.register(name="I", email="i@test.com")
        result = await rotate_token(
            store_a,
            admin_token_configured=_ADMIN,
            admin_token=_ADMIN,
            identifier=record["user_id"],
        )
        assert result["success"] is True
        assert result["new_token"] != record["token"]

    async def test_rotate_missing_returns_error(self, store_a):
        result = await rotate_token(
            store_a,
            admin_token_configured=_ADMIN,
            admin_token=_ADMIN,
            identifier="ghost-user",
        )
        assert result["success"] is False
        assert "error" in result
