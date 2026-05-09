"""ConfigClient — cliente HTTP para o config-mcp-server.

Módulo compartilhado importado por outros MCP servers para buscar credenciais
centralizadas e variáveis de ambiente sem depender de Claude como intermediário.

Uso nos outros MCPs:
    from shared.config_client import ConfigClient

    client = ConfigClient.from_env()  # lê CONFIG_MCP_API_PORT e CONFIG_MCP_API_TOKEN
    acr_user = client.get_credential("credentials.acr", "ACR_USERNAME")
    env_vars  = client.get_env_config("dev")

Comportamento de fallback:
    Se o config-mcp não estiver rodando (conexão recusada, timeout),
    todos os métodos retornam None/{} silenciosamente — o MCP caller
    deve então tentar suas próprias variáveis de ambiente.
"""
from __future__ import annotations

import os
from typing import Any

from .base_client import BaseHTTPClient


class ConfigClient(BaseHTTPClient):
    """Cliente HTTP para o config-mcp-server."""

    DEFAULT_TIMEOUT = 5.0

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7099",
        token: str = "",
        timeout: float | None = None,
        cache_ttl: float = 5.0,
    ) -> None:
        super().__init__(base_url=base_url, token=token, timeout=timeout, cache_ttl=cache_ttl)

    @classmethod
    def from_env(cls) -> ConfigClient:
        """Cria instância a partir de variáveis de ambiente."""
        port = int(os.getenv("CONFIG_MCP_API_PORT", "7099"))
        token = os.getenv("CONFIG_MCP_API_TOKEN", "")
        return cls(base_url=f"http://127.0.0.1:{port}", token=token)

    def get_credential(self, namespace: str, key: str) -> str | None:
        """Retorna o valor de uma credencial ou None se não disponível."""
        result = self._get(f"/credentials/{namespace}/{key}")
        return result["value"] if result else None

    def get_env_config(self, environment: str) -> dict[str, str]:
        """Retorna todas as variáveis de um ambiente ou {} se não disponível."""
        result = self._get(f"/env/{environment}")
        return result if isinstance(result, dict) else {}

    def get_tenant_config(self, tenant_id: str) -> dict[str, str]:
        """Retorna as variáveis de um tenant ou {} se não disponível."""
        result = self._get(f"/tenants/{tenant_id}")
        return result if isinstance(result, dict) else {}

    def get_physical_info(self) -> dict[str, Any]:
        """Retorna informações de hardware do host onde config-mcp roda."""
        return self._get("/physical") or {}

    def list_namespaces(self) -> list[str]:
        result = self._get("/namespaces")
        return result.get("namespaces", []) if result else []

    def list_tenants(self) -> list[str]:
        result = self._get("/tenants")
        return result.get("tenants", []) if result else []
