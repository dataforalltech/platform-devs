"""Regression guard for the removed single-file persistence runtime."""

from pathlib import Path


def test_legacy_package_resolves_to_trinity_sidecar():
    import project_product_mcp.server.mcp_server as server

    assert len(server._TOOL_SCHEMAS) == 13
    assert Path(server.__file__).as_posix().endswith("mcp/project_product_mcp/server/mcp_server.py")
