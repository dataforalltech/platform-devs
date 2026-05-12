"""Tests for MCP Gateway — auth, rate limiting, RBAC, audit logging."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from src.main import app
from src.auth.token_validator import validate_token, UserSession
from src.auth.rbac import is_authorized
from src.middleware.rate_limiter import check_rate_limit


class TestAuth:
    """Authentication tests."""

    @pytest.mark.asyncio
    async def test_validate_admin_token(self):
        """Test admin token validation."""
        result = await validate_token("test-admin-token")
        assert result is not None
        assert result.user_id == "admin"
        assert result.role == "admin"
        assert result.scopes == ["*"]

    @pytest.mark.asyncio
    async def test_validate_developer_token(self):
        """Test developer token validation."""
        result = await validate_token("test-developer-token")
        assert result is not None
        assert result.user_id == "dev1"
        assert result.role == "developer"
        assert "qazilla-mcp" in result.scopes

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        """Test invalid token returns None."""
        result = await validate_token("invalid-token-xyz")
        assert result is None


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
        assert is_authorized(user, "qazilla-mcp", "generate_unit_tests")
        assert is_authorized(user, "backzilla-mcp", "generate_service_layer")
        assert is_authorized(user, "any-mcp", "any-tool")

    def test_developer_has_limited_access(self):
        """Test developer has restricted access."""
        user = UserSession(
            user_id="dev1",
            role="developer",
            scopes=["qazilla-mcp", "backzilla-mcp"],
            tenant_id="test"
        )
        assert is_authorized(user, "qazilla-mcp", "generate_unit_tests")
        assert is_authorized(user, "backzilla-mcp", "generate_service_layer")
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
            assert any(m["name"] == "qazilla-mcp" for m in data["mcps"])

    def test_unauthorized_request(self):
        """Test request without auth token."""
        with TestClient(app) as client:
            response = client.get("/mcp/qazilla-mcp/tools")
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
