"""Role-Based Access Control for MCP tools."""
from __future__ import annotations

from src.auth.token_validator import UserSession

RBAC_MAP = {
    "admin": {
        "*": ["*"],
    },
    "developer": {
        "backzilla-mcp": ["*"],
        "archzilla-mcp": ["*"],
        "qazilla-mcp": ["generate_unit_tests", "generate_api_tests", "generate_test_plan"],
    },
    "data-scientist": {
        "qazilla-mcp": ["*"],
        "pozilla-mcp": ["analyze_product_problem", "calculate_rice_score"],
    },
    "product-owner": {
        "pozilla-mcp": ["*"],
    },
    "readonly": {
        "*": ["status"],
    },
}

def is_authorized(user: UserSession, mcp: str, tool: str) -> bool:
    """Check if user has permission to call tool on MCP."""
    allowed_tools = RBAC_MAP.get(user.role, {})

    # Check explicit MCP match
    mcp_tools = allowed_tools.get(mcp)
    if mcp_tools:
        if "*" in mcp_tools or tool in mcp_tools:
            return True

    # Check wildcard match
    mcp_tools = allowed_tools.get("*")
    if mcp_tools:
        if "*" in mcp_tools or tool in mcp_tools:
            return True

    return False
