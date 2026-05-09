"""Shared utilities for platform-devs MCP servers.

Este pacote consolida código compartilhado entre os 11 MCP servers
do platform-devs, eliminando duplicação de base_client, twin_client,
e config_client entre agent-twin e config servers.

Módulos:
- base_client: BaseHTTPClient com cache TTL
- twin_client: TwinClient para interagir com agent-twin-mcp
- config_client: ConfigClient para interagir com config-mcp

Uso típico:
    from shared.twin_client import TwinClient
    from shared.config_client import ConfigClient

    twin = TwinClient.from_env()
    config = ConfigClient.from_env()
"""
from .base_client import BaseHTTPClient
from .config_client import ConfigClient
from .twin_client import TwinClient

__all__ = [
    "BaseHTTPClient",
    "TwinClient",
    "ConfigClient",
]
