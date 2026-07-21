from pathlib import Path

import yaml

from project_product_mcp.server import mcp_server

ROOT = Path(__file__).resolve().parents[2]


def test_all_published_tools_have_runtime_input_and_output_contracts():
    manifest = yaml.safe_load(
        (ROOT / "manifests/mcps/project-product-mcp.yaml").read_text(encoding="utf-8")
    )
    contracts = {}
    for relative in manifest["tool_contracts"]:
        payload = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
        contracts[payload["name"]] = payload
    assert set(contracts) == set(mcp_server._TOOL_SCHEMAS)
    for name, runtime in mcp_server._TOOL_SCHEMAS.items():
        contract = contracts[name]
        assert runtime["schema"] == contract["input_schema"]
        assert runtime["output_schema"] == contract["output_schema"]
        assert runtime["required_scope"] == contract["required_scope"]
        assert runtime["capability"].startswith("portfolio.")


def test_dispatcher_covers_exactly_every_registered_tool():
    source = Path(mcp_server.__file__).read_text(encoding="utf-8")
    for name in mcp_server._TOOL_SCHEMAS:
        assert f'"{name}":' in source
    assert mcp_server._EXEMPT_TOOLS == frozenset()


def test_governance_action_classes_cover_runtime_capabilities_exactly():
    definitions = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "deploy/governance-action-classes.yaml").read_text(
            encoding="utf-8"
        )
    )["action_classes"]
    by_action_class = {item["action_class"]: item for item in definitions}

    capabilities = {metadata["capability"] for metadata in mcp_server._TOOL_SCHEMAS.values()}
    assert set(by_action_class) == capabilities
    for metadata in mcp_server._TOOL_SCHEMAS.values():
        definition = by_action_class[metadata["capability"]]
        assert definition["required_permission_codes"] == [
            metadata["required_scope"].replace(":", ".")
        ]
        assert definition["requires_audit"] is True


def test_rollout_manifest_uses_canonical_twin_and_readiness_contracts():
    manifest = yaml.safe_load(
        (ROOT / "manifests/mcps/project-product-mcp.yaml").read_text(encoding="utf-8")
    )
    assert manifest["runtime"]["build_secrets"] == ["github_token"]
    assert "build_ssh" not in manifest["runtime"]
    assert manifest["runtime"]["environment"]["MCP_TWIN_AUDIENCE"] == "mcp:portfolio"
    assert manifest["transport"]["canonical_http"]["health_ready"] == "/v1/ready"
