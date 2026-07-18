from __future__ import annotations

from pathlib import Path

import pytest
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
