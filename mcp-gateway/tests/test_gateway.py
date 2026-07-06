"""Tests for MCP Gateway — auth, rate limiting, RBAC, audit logging."""
import asyncio
import json
import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

import bcrypt

from src.main import app
from src.auth.token_validator import (
    validate_token,
    authenticate_request,
    UserSession,
)
from src.auth.rbac import is_authorized
from src.middleware.rate_limiter import check_rate_limit


def _make_static_env(raw_token, *, user_id, role, scopes, tenant_id,
                     expires_at=None, revoked=False):
    """Gera o JSON de GATEWAY_STATIC_TOKENS_JSON (forma de lista) para um token."""
    token_hash = bcrypt.hashpw(raw_token.encode(), bcrypt.gensalt()).decode()
    return json.dumps([
        {
            "token_hash": token_hash,
            "user_id": user_id,
            "role": role,
            "scopes": scopes,
            "tenant_id": tenant_id,
            "expires_at": expires_at,
            "revoked": revoked,
        }
    ])


class TestStaticTokenAuth:
    """Autenticação por static token (bootstrap) com bcrypt."""

    @pytest.mark.asyncio
    async def test_valid_static_token_returns_session(self, monkeypatch):
        """Token correto → UserSession com os campos do registro."""
        env = _make_static_env(
            "s3cret-admin-token",
            user_id="admin",
            role="admin",
            scopes=["*"],
            tenant_id="acme",
        )
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)

        result = await authenticate_request("Bearer s3cret-admin-token")
        assert result is not None
        assert result.user_id == "admin"
        assert result.role == "admin"
        assert result.scopes == ["*"]
        assert result.tenant_id == "acme"

    @pytest.mark.asyncio
    async def test_wrong_static_token_returns_none(self, monkeypatch):
        """Token errado (hash não bate) → None."""
        env = _make_static_env(
            "the-real-token",
            user_id="dev1",
            role="developer",
            scopes=["qa-engineer-mcp"],
            tenant_id="acme",
        )
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)

        assert await authenticate_request("Bearer wrong-token") is None

    @pytest.mark.asyncio
    async def test_expired_static_token_returns_none(self, monkeypatch):
        """Token expirado → None."""
        env = _make_static_env(
            "expired-token",
            user_id="dev1",
            role="developer",
            scopes=["qa-engineer-mcp"],
            tenant_id="acme",
            expires_at=int(time.time()) - 10,
        )
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)

        assert await validate_token("expired-token") is None

    @pytest.mark.asyncio
    async def test_revoked_static_token_returns_none(self, monkeypatch):
        """Token revogado → None."""
        env = _make_static_env(
            "revoked-token",
            user_id="dev1",
            role="developer",
            scopes=["qa-engineer-mcp"],
            tenant_id="acme",
            revoked=True,
        )
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)

        assert await validate_token("revoked-token") is None

    @pytest.mark.asyncio
    async def test_map_form_env(self, monkeypatch):
        """Suporta a forma de mapa {hash: registro}."""
        token_hash = bcrypt.hashpw(b"map-token", bcrypt.gensalt()).decode()
        env = json.dumps({
            token_hash: {
                "user_id": "dev2",
                "role": "developer",
                "scopes": ["backend-mcp"],
                "tenant_id": "acme",
            }
        })
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)

        result = await validate_token("map-token")
        assert result is not None
        assert result.user_id == "dev2"
        assert "backend-mcp" in result.scopes

    @pytest.mark.asyncio
    async def test_old_test_tokens_removed(self, monkeypatch):
        """GARANTIA DE REMOÇÃO: os tokens de teste antigos não valem mais."""
        # Sem env configurada e/ou com env vazia, nada deve autenticar.
        monkeypatch.delenv("GATEWAY_STATIC_TOKENS_JSON", raising=False)
        assert await validate_token("test-admin-token") is None
        assert await validate_token("test-developer-token") is None

        # Mesmo com uma store válida para outro usuário, os antigos continuam None.
        env = _make_static_env(
            "real-token",
            user_id="admin",
            role="admin",
            scopes=["*"],
            tenant_id="acme",
        )
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)
        assert await validate_token("test-admin-token") is None
        assert await validate_token("test-developer-token") is None

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_returns_none(self, monkeypatch):
        """Header sem 'Bearer ' → None."""
        env = _make_static_env(
            "tok", user_id="u", role="admin", scopes=["*"], tenant_id="acme"
        )
        monkeypatch.setenv("GATEWAY_STATIC_TOKENS_JSON", env)
        assert await authenticate_request("tok") is None
        assert await authenticate_request(None) is None


class TestJwtAuth:
    """Autenticação por JWT (produção) validada por chave pública PEM injetável."""

    @pytest.mark.asyncio
    async def test_valid_jwt_returns_session(self, monkeypatch):
        """JWT com aud/iss corretos e assinatura válida → UserSession."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import jwt as pyjwt

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        issuer = "https://auth.example.com"
        resource = "https://gateway.example.com"

        now = int(time.time())
        token = pyjwt.encode(
            {
                "iss": issuer,
                "sub": "user-42",
                "aud": resource,
                "iat": now,
                "nbf": now,
                "exp": now + 3600,
                "scope": "qa-engineer-mcp backend-mcp",
                "role": "developer",
                "tenant_id": "acme",
            },
            private_pem,
            algorithm="RS256",
        )

        monkeypatch.setenv("GATEWAY_AS_ISSUER", issuer)
        monkeypatch.setenv("GATEWAY_RESOURCE", resource)
        monkeypatch.setenv("GATEWAY_AS_PUBLIC_KEY_PEM", public_pem)
        monkeypatch.delenv("GATEWAY_AS_JWKS_URL", raising=False)

        result = await authenticate_request(f"Bearer {token}")
        assert result is not None
        assert result.user_id == "user-42"
        assert result.role == "developer"
        assert result.tenant_id == "acme"
        assert "qa-engineer-mcp" in result.scopes
        assert "backend-mcp" in result.scopes

    @pytest.mark.asyncio
    async def test_jwt_wrong_audience_returns_none(self, monkeypatch):
        """JWT com aud errado → None."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import jwt as pyjwt

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        issuer = "https://auth.example.com"
        now = int(time.time())
        token = pyjwt.encode(
            {
                "iss": issuer,
                "sub": "user-42",
                "aud": "https://OTHER-resource.example.com",
                "iat": now,
                "exp": now + 3600,
                "scope": "qa-engineer-mcp",
            },
            private_pem,
            algorithm="RS256",
        )

        monkeypatch.setenv("GATEWAY_AS_ISSUER", issuer)
        monkeypatch.setenv("GATEWAY_RESOURCE", "https://gateway.example.com")
        monkeypatch.setenv("GATEWAY_AS_PUBLIC_KEY_PEM", public_pem)
        monkeypatch.delenv("GATEWAY_AS_JWKS_URL", raising=False)

        assert await validate_token(token) is None


class TestRBAC:
    """RBAC authorization tests."""

    def test_admin_can_access_all(self):
        """Test admin has access to all MCPs and tools."""
        user = UserSession(
            user_id="admin",
            role="admin",
            scopes=["*"],
            tenant_id="test"
        )
        assert is_authorized(user, "qa-engineer-mcp", "generate_unit_tests")
        assert is_authorized(user, "backend-mcp", "generate_service_layer")
        assert is_authorized(user, "any-mcp", "any-tool")

    def test_developer_has_limited_access(self):
        """Test developer has restricted access."""
        user = UserSession(
            user_id="dev1",
            role="developer",
            scopes=["qa-engineer-mcp", "backend-mcp"],
            tenant_id="test"
        )
        assert is_authorized(user, "qa-engineer-mcp", "generate_unit_tests")
        assert is_authorized(user, "backend-mcp", "generate_service_layer")
        assert not is_authorized(user, "infra-mcp", "generate_adr")

    def test_readonly_access(self):
        """Test readonly user has very limited access."""
        user = UserSession(
            user_id="readonly_user",
            role="readonly",
            scopes=["*"],
            tenant_id="test"
        )
        assert is_authorized(user, "any-mcp", "status")
        assert not is_authorized(user, "any-mcp", "deploy")


class TestGateway:
    """Gateway endpoint tests."""

    def test_health_endpoint(self):
        """Test health check endpoint."""
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"

    def test_root_endpoint(self):
        """Test root endpoint returns service info."""
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert data["service"] == "mcp-gateway"
            assert "endpoints" in data

    def test_list_mcps_endpoint(self):
        """Test MCP listing endpoint."""
        with TestClient(app) as client:
            response = client.get("/mcp")
            assert response.status_code == 200
            data = response.json()
            assert "mcps" in data
            assert len(data["mcps"]) > 0
            assert any(m["name"] == "qa-engineer-mcp" for m in data["mcps"])

    def test_unauthorized_request(self):
        """Test request without auth token."""
        with TestClient(app) as client:
            response = client.get("/mcp/qa-engineer-mcp/tools")
            assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_rate_limiter_basic(self):
        """Test rate limiting doesn't crash (mock Redis)."""
        with patch("src.middleware.rate_limiter.get_redis") as mock_redis:
            mock_client = AsyncMock()
            mock_client.incr.return_value = 1
            mock_redis.return_value = mock_client

            # Should not raise
            await check_rate_limit("user123", "admin")
            mock_client.incr.assert_called()


class TestAuditLogging:
    """Audit logging integration tests."""

    def test_audit_table_init(self):
        """Test audit table can be initialized."""
        from src.middleware.audit_logger import init_audit_table
        # Should not raise even without actual PostgreSQL
        try:
            init_audit_table()
        except Exception as e:
            # Expected if no PostgreSQL running
            assert "psycopg2" in str(type(e)) or "connection" in str(e).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
