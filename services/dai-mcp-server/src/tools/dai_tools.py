"""DAI tools — invoke DAI orchestrator as agent."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def dai_chat(message: str, context: dict[str, Any] | None = None) -> str:
    """Send message to DAI orchestrator and get response."""
    try:
        payload = {"message": message, "context": context or {}}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DAI_BASE_URL}/chat",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_analyze(objective: str, data: dict[str, Any]) -> str:
    """Ask DAI to analyze data for a specific objective."""
    try:
        payload = {"objective": objective, "data": data}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DAI_BASE_URL}/analyze",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_generate_workflow(objective: str, constraints: dict[str, Any] | None = None) -> str:
    """Ask DAI to generate workflow for specific objective."""
    try:
        payload = {"objective": objective, "constraints": constraints or {}}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DAI_BASE_URL}/workflow/generate",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_execute_workflow(workflow_id: str, inputs: dict[str, Any] | None = None) -> str:
    """Execute workflow via DAI orchestrator."""
    try:
        payload = {"inputs": inputs or {}}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DAI_BASE_URL}/workflow/{workflow_id}/execute",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Workflow {workflow_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_get_session_history(session_id: str) -> str:
    """Get session history and memory from DAI."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/sessions/{session_id}/history",
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Session {session_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_get_knowledge_base(query: str, kb_type: str = "business") -> str:
    """Query DAI knowledge base (business or technical)."""
    try:
        params = {"q": query, "type": kb_type}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/kb/search",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_get_workflow_status(execution_id: str) -> str:
    """Get workflow execution status (pending|running|completed|failed) with progress and results."""
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/workflow-executions/{execution_id}",
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Execution {execution_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_list_workflows(tenant_id: str) -> str:
    """List all available workflows for a tenant."""
    try:
        params = {"tenant_id": tenant_id}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/workflows",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_get_profile(tenant_id: str, user_id: str) -> str:
    """Get user profile (type, LLM model, risk max level)."""
    try:
        params = {"tenant_id": tenant_id, "user_id": user_id}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/profiles/{user_id}",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Profile for user {user_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_set_profile(tenant_id: str, user_id: str, profile_type: str) -> str:
    """Set user profile type (data_engineer, analyst, data_scientist, admin)."""
    try:
        payload = {"profile_type": profile_type}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DAI_BASE_URL}/profiles/{user_id}",
                json=payload,
                params={"tenant_id": tenant_id},
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"User {user_id} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_get_session_history(tenant_id: str, user_id: str, limit: int = 50) -> str:
    """Get session history for a user."""
    try:
        params = {"tenant_id": tenant_id, "user_id": user_id, "limit": limit}
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/session-history",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def dai_audit_log(tenant_id: str, filter_action: str | None = None, limit: int = 100) -> str:
    """Get audit log with optional action filter."""
    try:
        params = {"tenant_id": tenant_id, "limit": limit}
        if filter_action:
            params["filter_action"] = filter_action
        async with httpx.AsyncClient(timeout=settings.MCP_DAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DAI_BASE_URL}/audit-log",
                params=params,
                headers={"Authorization": f"Bearer {settings.MCP_DAI_API_KEY}"},
            )
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
