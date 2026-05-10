"""Datalake tools — 8 core tools for database, schema, and table operations."""

import json
from typing import Any

import httpx

from src.config.settings import settings


async def list_schemas(database: str) -> str:
    """List all schemas in a database.

    Args:
        database: Database name

    Returns: JSON with list of schema names
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Database {database} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def list_tables(database: str, schema: str) -> str:
    """List all tables in a schema.

    Args:
        database: Database name
        schema: Schema name

    Returns: JSON with table information
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas/{schema}/tables",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Schema {schema} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def get_table_schema(database: str, schema: str, table: str) -> str:
    """Get column definitions for a table.

    Args:
        database: Database name
        schema: Schema name
        table: Table name

    Returns: JSON with column details
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas/{schema}/tables/{table}/schema",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Table {table} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def create_table(database: str, schema: str, table: str, columns: list[dict[str, Any]]) -> str:
    """Create a new table.

    Args:
        database: Database name
        schema: Schema name
        table: Table name
        columns: List of column definitions {name, type, nullable}

    Returns: JSON with table creation result
    """
    try:
        payload = {"table": table, "columns": columns}
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas/{schema}/tables",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 400:
                return json.dumps({"error": "BadRequest", "details": resp.text})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def drop_table(database: str, schema: str, table: str) -> str:
    """Drop (delete) a table.

    Args:
        database: Database name
        schema: Schema name
        table: Table name

    Returns: JSON with deletion status
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.delete(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas/{schema}/tables/{table}",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Table {table} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def query_data(database: str, sql: str, limit: int = 1000) -> str:
    """Execute a query and return data.

    Args:
        database: Database name
        sql: SQL query string
        limit: Maximum rows to return

    Returns: JSON with query results
    """
    try:
        payload = {"sql": sql, "limit": limit}
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS * 2) as client:
            resp = await client.post(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/query",
                json=payload,
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 400:
                return json.dumps({"error": "BadRequest", "details": resp.text})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def validate_table(database: str, schema: str, table: str) -> str:
    """Validate table integrity and constraints.

    Args:
        database: Database name
        schema: Schema name
        table: Table name

    Returns: JSON with validation results
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas/{schema}/tables/{table}/validate",
                json={},
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Table {table} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})


async def get_table_stats(database: str, schema: str, table: str) -> str:
    """Get statistics for a table.

    Args:
        database: Database name
        schema: Schema name
        table: Table name

    Returns: JSON with table statistics
    """
    try:
        async with httpx.AsyncClient(timeout=settings.MCP_DATALAKE_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{settings.MCP_DATALAKE_BASE_URL}/databases/{database}/schemas/{schema}/tables/{table}/stats",
                headers={"Authorization": f"Bearer {settings.MCP_DATALAKE_API_KEY}"},
                verify=settings.MCP_DATALAKE_VERIFY_SSL,
            )
            if resp.status_code == 404:
                return json.dumps({"error": "NotFound", "details": f"Table {table} not found"})
            resp.raise_for_status()
            return json.dumps({"status": "ok", "data": resp.json()})
    except httpx.HTTPError as e:
        return json.dumps({"error": "HTTPError", "details": str(e)})
    except Exception as e:
        return json.dumps({"error": "Exception", "details": str(e)})
