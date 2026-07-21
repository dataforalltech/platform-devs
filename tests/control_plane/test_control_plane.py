from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.control_plane.artifact_generator import (
    check_all,
    render_compose,
    render_mcp_json,
    render_runtime_registry,
)
from src.control_plane.inventory import audit_inventory
from src.control_plane.manifest_loader import load_catalog
from src.control_plane.manifest_models import MCPManifest, ToolContract
from src.control_plane.manifest_validator import validate_catalog

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(ROOT)


def test_catalog_is_valid_and_inventory_is_complete(catalog) -> None:
    assert validate_catalog(catalog) == []
    assert audit_inventory(catalog).uncovered_directories == []


def test_generated_artifacts_have_no_drift(catalog) -> None:
    assert check_all(catalog) == []


def test_project_product_runtime_supports_local_and_remote_resolution(catalog) -> None:
    registry = json.loads(render_runtime_registry(catalog))["services"][
        "project-product-mcp"
    ]
    assert registry["url"] == "http://project-product-mcp:7121"
    assert registry["url_env"] == "PROJECT_PRODUCT_MCP_URL"

    compose = yaml.safe_load(render_compose(catalog))
    service = compose["services"]["project-product-mcp"]
    assert "volumes" not in service
    assert service["depends_on"] == ["platform-project-product-api", "redis"]
    assert service["build"]["secrets"] == ["github_token"]
    assert "ssh" not in service["build"]
    assert service["command"] == [
        "python",
        "-m",
        "project_product_mcp.server.mcp_server",
    ]
    assert compose["secrets"]["github_token"] == {
        "file": "${GITHUB_TOKEN_FILE:?required}"
    }
    assert service["environment"]["SERVICE_BASE_URL"] == "http://platform-project-product-api:8000"
    assert service["environment"]["MCP_TWIN_AUDIENCE"] == "mcp:portfolio"
    api = compose["services"]["platform-project-product-api"]
    assert api["command"] == ["python", "-m", "app.main"]
    gateway_environment = compose["services"]["mcp-gateway"]["environment"]
    assert gateway_environment["PROJECT_PRODUCT_MCP_URL"] == "${PROJECT_PRODUCT_MCP_URL:-}"


def test_planned_and_disabled_entries_never_enter_runtime(catalog) -> None:
    runtime_outputs = "\n".join(
        (
            render_mcp_json(catalog),
            render_runtime_registry(catalog),
            render_compose(catalog),
        )
    )
    for manifest in catalog.manifests.values():
        if manifest.status in {"planned", "experimental", "disabled", "deprecated"}:
            assert manifest.id not in runtime_outputs


def test_planned_manifest_cannot_enable_runtime_surface() -> None:
    payload = {
        "id": "future-mcp",
        "display_name": "Future MCP",
        "description": "future",
        "status": "planned",
        "classification": {"type": "domain", "capability_domain": "future"},
        "ownership": {"team": "platform", "source_repo": "example/repo"},
        "runtime": {"mode": "none", "exposes_tools": False},
        "transport": {},
        "security": {
            "auth_required": False,
            "tenant_required": False,
            "policy_mode": "not_applicable",
            "audit_required": False,
            "secret_redaction_required": True,
            "context_signing_required": False,
        },
        "ci": {"enabled": False},
        "gateway": {"enabled": True},
        "registry": {"enabled": False},
    }
    with pytest.raises(ValidationError, match="planned manifests cannot be enabled"):
        MCPManifest.model_validate(payload)


def test_build_ssh_and_build_secrets_are_mutually_exclusive() -> None:
    with pytest.raises(
        ValidationError, match="build_ssh and build_secrets are mutually exclusive"
    ):
        MCPManifest.model_validate(
            {
                "id": "conflicting-build-mcp",
                "display_name": "Conflicting build MCP",
                "description": "invalid build configuration",
                "status": "disabled",
                "classification": {
                    "type": "domain",
                    "capability_domain": "test",
                },
                "ownership": {"team": "platform", "source_repo": "example/repo"},
                "runtime": {
                    "mode": "none",
                    "build_ssh": True,
                    "build_secrets": ["github_token"],
                    "exposes_tools": False,
                },
                "transport": {},
                "security": {
                    "auth_required": False,
                    "tenant_required": False,
                    "policy_mode": "not_applicable",
                    "audit_required": False,
                    "secret_redaction_required": True,
                    "context_signing_required": False,
                },
                "ci": {"enabled": False},
                "gateway": {"enabled": False},
                "registry": {"enabled": False},
            }
        )


def test_secret_bearing_tool_contract_is_rejected() -> None:
    payload = {
        "provider_id": "devteam-mcp",
        "name": "leak_secret",
        "description": "unsafe",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {"private_key_pem": {"type": "string"}},
        },
        "required_scope": "secret:read",
        "mutating": False,
        "risk": {
            "level": "critical",
            "effects": ["secret_access"],
            "blast_radius": "tenant",
            "approval_required": "N2",
        },
    }
    with pytest.raises(ValidationError, match="secret-bearing field is forbidden"):
        ToolContract.model_validate(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "credentials",
        "secrets",
        "passwords",
        "passphrase",
        "api_key",
        "ssh_key",
        "access_token",
        "access_keys",
    ],
)
def test_secret_bearing_field_name_variants_are_rejected(field_name: str) -> None:
    payload = {
        "provider_id": "devteam-mcp",
        "name": "leak_secret",
        "description": "unsafe",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {field_name: {"type": "string"}},
        },
        "required_scope": "secret:read",
        "mutating": False,
        "risk": {
            "level": "critical",
            "effects": ["secret_access"],
            "blast_radius": "tenant",
            "approval_required": "N2",
        },
    }
    with pytest.raises(ValidationError, match="secret-bearing field is forbidden"):
        ToolContract.model_validate(payload)


def test_opaque_reference_field_names_are_allowed() -> None:
    payload = {
        "provider_id": "devteam-mcp",
        "name": "safe_reference",
        "description": "safe",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {"credential_ref": {"type": "string"}, "lease_id": {"type": "string"}},
        },
        "required_scope": "resource:read",
        "mutating": False,
        "risk": {
            "level": "low",
            "effects": ["read"],
            "blast_radius": "tenant",
            "approval_required": "none",
        },
    }
    assert ToolContract.model_validate(payload).secret_reference_only is True


def test_high_risk_tool_requires_approval() -> None:
    payload = {
        "provider_id": "devteam-mcp",
        "name": "dangerous_write",
        "description": "unsafe",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {}},
        "required_scope": "danger:write",
        "mutating": True,
        "risk": {
            "level": "high",
            "effects": ["delete"],
            "blast_radius": "tenant",
            "approval_required": "none",
        },
    }
    with pytest.raises(ValidationError, match="high/critical tools require approval"):
        ToolContract.model_validate(payload)
