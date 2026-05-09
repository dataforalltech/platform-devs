"""Camada de protocolo MCP — única dependência direta do SDK mcp."""

from .mcp_server import build_server, main

__all__ = ["build_server", "main"]
