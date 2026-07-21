"""Governed tools for inspecting and validating canonical MCP contracts."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(os.environ.get("PLATFORM_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from shared.secure_runtime import ToolDefinition, TrustedContext, create_mcp_app  # noqa: E402
from src.control_plane.manifest_loader import load_catalog  # noqa: E402
from src.control_plane.manifest_validator import validate_catalog  # noqa: E402


def _contract_payload(provider_id: str, name: str, contract: Any) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "name": name,
        "description": contract.description,
        "status": contract.status,
        "required_scope": contract.required_scope,
        "mutating": contract.mutating,
        "risk": contract.risk.model_dump(mode="json"),
        "secret_reference_only": contract.secret_reference_only,
        "input_schema": contract.input_schema,
        "output_schema": contract.output_schema,
    }


def list_contracts(arguments: dict[str, Any], _: TrustedContext) -> dict[str, Any]:
    catalog = load_catalog(REPOSITORY_ROOT)
    provider_filter = arguments.get("provider_id")
    status_filter = arguments.get("status")
    contracts = [
        _contract_payload(provider_id, name, contract)
        for (provider_id, name), contract in sorted(catalog.contracts.items())
        if (provider_filter is None or provider_id == provider_filter)
        and (status_filter is None or contract.status == status_filter)
    ]
    return {"count": len(contracts), "contracts": contracts}


def get_contract(arguments: dict[str, Any], _: TrustedContext) -> dict[str, Any]:
    catalog = load_catalog(REPOSITORY_ROOT)
    key = (arguments["provider_id"], arguments["name"])
    contract = catalog.contracts.get(key)
    if contract is None:
        return {"found": False, "contract": None}
    return {"found": True, "contract": _contract_payload(*key, contract)}


def validate_contract_catalog(_: dict[str, Any], __: TrustedContext) -> dict[str, Any]:
    catalog = load_catalog(REPOSITORY_ROOT)
    errors = validate_catalog(catalog)
    executable = [item for item in catalog.manifests.values() if item.status in {"active", "experimental"}]
    providers_with_contracts = {provider_id for provider_id, _ in catalog.contracts}
    return {
        "valid": not errors,
        "errors": errors,
        "manifest_count": len(catalog.manifests),
        "executable_provider_count": len(executable),
        "contract_count": len(catalog.contracts),
        "providers_with_contracts": len(providers_with_contracts),
    }


CONTRACT_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "provider_id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "status": {"type": "string", "enum": ["active", "disabled"]},
        "required_scope": {"type": "string"},
        "mutating": {"type": "boolean"},
        "risk": {"type": "object"},
        "secret_reference_only": {"type": "boolean"},
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    },
    "required": [
        "provider_id", "name", "description", "status", "required_scope", "mutating",
        "risk", "secret_reference_only", "input_schema", "output_schema",
    ],
}

TOOLS = [
    ToolDefinition(
        name="contracts_list",
        description="List canonical governed tool contracts with optional provider and status filters.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "provider_id": {"type": "string", "minLength": 1},
                "status": {"type": "string", "enum": ["active", "disabled"]},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "count": {"type": "integer", "minimum": 0},
                "contracts": {"type": "array", "items": CONTRACT_PAYLOAD_SCHEMA},
            },
            "required": ["count", "contracts"],
        },
        required_scope="contracts:read",
        mutating=False,
        risk_level="low",
        handler=list_contracts,
    ),
    ToolDefinition(
        name="contracts_get",
        description="Read one canonical governed tool contract by provider and tool name.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"provider_id": {"type": "string", "minLength": 1}, "name": {"type": "string", "minLength": 1}},
            "required": ["provider_id", "name"],
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"found": {"type": "boolean"}, "contract": {"anyOf": [CONTRACT_PAYLOAD_SCHEMA, {"type": "null"}]}},
            "required": ["found", "contract"],
        },
        required_scope="contracts:read",
        mutating=False,
        risk_level="low",
        handler=get_contract,
    ),
    ToolDefinition(
        name="contracts_validate_catalog",
        description="Validate all canonical MCP manifests and tool-contract references.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "valid": {"type": "boolean"},
                "errors": {"type": "array", "items": {"type": "string"}},
                "manifest_count": {"type": "integer", "minimum": 0},
                "executable_provider_count": {"type": "integer", "minimum": 0},
                "contract_count": {"type": "integer", "minimum": 0},
                "providers_with_contracts": {"type": "integer", "minimum": 0},
            },
            "required": ["valid", "errors", "manifest_count", "executable_provider_count", "contract_count", "providers_with_contracts"],
        },
        required_scope="contracts:validate",
        mutating=False,
        risk_level="low",
        handler=validate_contract_catalog,
    ),
]

app = create_mcp_app("contracts-mcp", TOOLS, readiness=lambda: load_catalog(REPOSITORY_ROOT))


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "7119")))


if __name__ == "__main__":
    main()
