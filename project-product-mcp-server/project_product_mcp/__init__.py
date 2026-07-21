"""Compatibility namespace that resolves to the canonical Trinity MCP package."""

from pathlib import Path

_canonical = Path(__file__).resolve().parents[1] / "mcp" / "project_product_mcp"
if str(_canonical) not in __path__:
    __path__.insert(0, str(_canonical))
