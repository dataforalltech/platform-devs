"""BackZilla MCP Server — Backend Engineering Specialist."""
from __future__ import annotations

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.backzilla_tools import (
    analyze_backend_requirement, generate_api_contract, generate_auth_policy,
    generate_database_schema, generate_fastapi_router, generate_nestjs_controller,
    generate_migration, generate_repository_layer, generate_service_layer,
    generate_openapi_spec, map_integration_flow, optimize_query, review_backend_code,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "analyze_backend_requirement": {"description": "Analisa requisito", "schema": {"type": "object", "properties": {"requirement": {"type": "string"}}, "required": ["requirement"]}},
    "generate_api_contract": {"description": "API contract", "schema": {"type": "object", "properties": {"endpoint": {"type": "string"}, "method": {"type": "string"}, "description": {"type": "string"}}, "required": ["endpoint", "method", "description"]}},
    "generate_auth_policy": {"description": "Auth policy", "schema": {"type": "object", "properties": {"resource": {"type": "string"}, "auth_type": {"type": "string"}, "roles": {"type": "array"}}, "required": ["resource", "auth_type", "roles"]}},
    "generate_database_schema": {"description": "DB schema", "schema": {"type": "object", "properties": {"entity": {"type": "string"}, "attributes": {"type": "array"}, "database": {"type": "string"}}, "required": ["entity", "attributes", "database"]}},
    "generate_fastapi_router": {"description": "FastAPI router", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "base_path": {"type": "string"}}, "required": ["name", "base_path"]}},
    "generate_nestjs_controller": {"description": "NestJS controller", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "base_path": {"type": "string"}}, "required": ["name", "base_path"]}},
    "generate_migration": {"description": "Migration", "schema": {"type": "object", "properties": {"title": {"type": "string"}, "operations": {"type": "array"}, "database": {"type": "string"}}, "required": ["title", "operations", "database"]}},
    "generate_repository_layer": {"description": "Repository", "schema": {"type": "object", "properties": {"entity": {"type": "string"}, "database": {"type": "string"}}, "required": ["entity", "database"]}},
    "generate_service_layer": {"description": "Service", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "methods": {"type": "array"}}, "required": ["name", "methods"]}},
    "generate_openapi_spec": {"description": "OpenAPI", "schema": {"type": "object", "properties": {"api_name": {"type": "string"}, "version": {"type": "string"}, "endpoints": {"type": "array"}}, "required": ["api_name", "version", "endpoints"]}},
    "map_integration_flow": {"description": "Integration", "schema": {"type": "object", "properties": {"integration_name": {"type": "string"}, "external_service": {"type": "string"}}, "required": ["integration_name", "external_service"]}},
    "optimize_query": {"description": "Query opt", "schema": {"type": "object", "properties": {"query": {"type": "string"}, "database": {"type": "string"}}, "required": ["query", "database"]}},
    "review_backend_code": {"description": "Code review", "schema": {"type": "object", "properties": {"code": {"type": "string"}, "language": {"type": "string"}}, "required": ["code", "language"]}},
}

_DISPATCH = {
    "analyze_backend_requirement": lambda a: analyze_backend_requirement(a["requirement"], a.get("context")),
    "generate_api_contract": lambda a: generate_api_contract(a["endpoint"], a["method"], a["description"], a.get("request_schema"), a.get("response_schema")),
    "generate_auth_policy": lambda a: generate_auth_policy(a["resource"], a["auth_type"], a["roles"], a.get("data_sensitivity")),
    "generate_database_schema": lambda a: generate_database_schema(a["entity"], a["attributes"], a["database"], a.get("relationships")),
    "generate_fastapi_router": lambda a: generate_fastapi_router(a["name"], a["base_path"], a.get("endpoints")),
    "generate_nestjs_controller": lambda a: generate_nestjs_controller(a["name"], a["base_path"], a.get("methods")),
    "generate_migration": lambda a: generate_migration(a["title"], a["operations"], a["database"]),
    "generate_repository_layer": lambda a: generate_repository_layer(a["entity"], a["database"], a.get("orm")),
    "generate_service_layer": lambda a: generate_service_layer(a["name"], a["methods"], a.get("dependencies")),
    "generate_openapi_spec": lambda a: generate_openapi_spec(a["api_name"], a["version"], a["endpoints"], a.get("base_url")),
    "map_integration_flow": lambda a: map_integration_flow(a["integration_name"], a["external_service"], a.get("endpoints"), a.get("auth_type")),
    "optimize_query": lambda a: optimize_query(a["query"], a["database"], a.get("table_schema")),
    "review_backend_code": lambda a: review_backend_code(a["code"], a["language"], a.get("focus")),
}

def main() -> None:
    server = HybridMCPServer("backzilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=7100))

if __name__ == "__main__":
    main()
