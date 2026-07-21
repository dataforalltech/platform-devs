#!/usr/bin/env python3
"""Generate canonical contracts and catalog records for project-product-mcp."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "project-product-mcp-server"
sys.path[:0] = [str(SERVICE / "mcp"), str(SERVICE), str(ROOT)]

from project_product_mcp.server.mcp_server import _TOOL_SCHEMAS  # noqa: E402

PROVIDER_ID = "project-product-mcp"
DOMAIN = "portfolio"


@dataclass(frozen=True)
class ToolAsset:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_scope: str
    mutating: bool
    risk_level: str
    approval_required: str


def _tool_assets() -> tuple[ToolAsset, ...]:
    assets: list[ToolAsset] = []
    for name, metadata in _TOOL_SCHEMAS.items():
        mutating = not metadata["required_scope"].endswith(":read")
        high_risk = name.endswith(("_delete", "_detach"))
        assets.append(
            ToolAsset(
                name=name,
                description=metadata["description"],
                input_schema=metadata["schema"],
                output_schema=metadata["output_schema"],
                required_scope=metadata["required_scope"],
                mutating=mutating,
                risk_level="high" if high_risk else ("medium" if mutating else "low"),
                approval_required="N2" if high_risk else "none",
            )
        )
    return tuple(assets)


TOOLS = _tool_assets()


def _plain(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload))


def _risk(tool: Any) -> dict[str, Any]:
    effect = (
        "delete"
        if tool.approval_required != "none"
        else ("write" if tool.mutating else "read")
    )
    return {
        "level": tool.risk_level,
        "effects": [effect],
        "blast_radius": "tenant" if tool.mutating else "none",
        "approval_required": tool.approval_required,
    }


def _resource(name: str) -> str:
    if name.startswith("product_"):
        return "product"
    if name.startswith("project_repository_"):
        return "repository-binding"
    return "project"


def _operation(name: str) -> str:
    return name.rsplit("_", 1)[-1]


def _render(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(_plain(payload), sort_keys=False, allow_unicode=True)


def expected_files() -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    provider = {
        "apiVersion": "catalog.platform.dev/v1",
        "kind": "Provider",
        "metadata": {
            "name": PROVIDER_ID,
            "uid": PROVIDER_ID,
            "domain": DOMAIN,
            "title": "Project & Product MCP",
            "description": "Tenant-scoped canonical products, projects and repository bindings.",
            "owner": "platform-engineering",
            "tags": ["portfolio", "products", "projects", "repositories"],
            "lifecycle": "stable",
            "version": "1.0.0",
        },
        "spec": {
            "server": "project-product-mcp-server",
            "kind": "mcp-server",
            "transport": "streamable-http",
            "version": "1.0.0",
        },
        "relations": [{"verb": "depends-on", "target": "connectors-mcp"}],
    }
    outputs[ROOT / "platform-catalog/catalog/providers/project-product-mcp.yaml"] = (
        _render(provider)
    )

    for tool in TOOLS:
        dashed = tool.name.replace("_", "-")
        risk = _risk(tool)
        contract = {
            "schema_version": 1,
            "provider_id": PROVIDER_ID,
            "name": tool.name,
            "description": tool.description,
            "status": "active",
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "required_scope": tool.required_scope,
            "mutating": tool.mutating,
            "risk": risk,
            "secret_reference_only": True,
        }
        outputs[ROOT / f"contracts/tools/project-product-mcp-{dashed}.yaml"] = _render(
            contract
        )

        operation_id = f"{DOMAIN}.{tool.name}"
        resource = _resource(tool.name)
        verb = _operation(tool.name)
        authz = "write" if tool.mutating else "read"
        operation = {
            "apiVersion": "catalog.platform.dev/v1",
            "kind": "Operation",
            "metadata": {
                "name": f"{DOMAIN}/{tool.name}",
                "uid": operation_id,
                "domain": DOMAIN,
                "title": tool.name.replace("_", " "),
                "description": tool.description,
                "owner": "platform-engineering",
                "tags": [DOMAIN, resource, authz],
                "lifecycle": "stable",
                "version": "1.0.0",
            },
            "spec": {
                "domain": DOMAIN,
                "capability": "project-product-registry",
                "resource": {"type": resource, "parent": None, "namespace": None},
                "operation": verb,
                "authz": authz,
                "risk": {
                    "effects": risk["effects"],
                    "requires": []
                    if tool.approval_required == "none"
                    else [f"approval:{tool.approval_required}"],
                    "blast_radius": risk["blast_radius"],
                    "default_level": risk["level"],
                    "approval_required": risk["approval_required"],
                },
                "contract": {
                    "inputs": {},
                    "outputs": {},
                    "preconditions": ["trusted tenant context"],
                    "postconditions": ["tenant-scoped audit record"],
                    "execution": {
                        "idempotent": True,
                        "side_effects": tool.mutating,
                        "is_async": False,
                        "streaming": False,
                        "timeout_s": 60,
                        "retry_policy": "idempotency-key"
                        if tool.mutating
                        else "read-only",
                    },
                },
            },
            "relations": [{"verb": "acts-on", "target": f"resource:{resource}"}],
        }
        outputs[
            ROOT / f"platform-catalog/catalog/operations/portfolio__{tool.name}.yaml"
        ] = _render(operation)

        catalog_tool = {
            "apiVersion": "catalog.platform.dev/v1",
            "kind": "Tool",
            "metadata": {
                "name": f"{PROVIDER_ID}/{tool.name}",
                "uid": f"{PROVIDER_ID}:{tool.name}",
                "domain": DOMAIN,
                "title": f"{tool.name} @ {PROVIDER_ID}",
                "description": tool.description,
                "owner": "platform-engineering",
                "tags": [PROVIDER_ID, DOMAIN, resource],
                "lifecycle": "stable",
                "version": "1.0.0",
            },
            "spec": {
                "operation_id": operation_id,
                "provider_id": PROVIDER_ID,
                "provider_version": "1.0.0",
                "tool": tool.name,
                "endpoint": "streamable-http",
                "selection": {},
            },
            "relations": [
                {"verb": "implements", "target": operation_id},
                {"verb": "provided-by", "target": PROVIDER_ID},
            ],
        }
        outputs[
            ROOT / f"platform-catalog/catalog/tools/project-product-mcp-{dashed}.yaml"
        ] = _render(catalog_tool)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drift: list[str] = []
    for path, expected in expected_files().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                drift.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    if drift:
        print("project-product generated asset drift:")
        for item in drift:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
