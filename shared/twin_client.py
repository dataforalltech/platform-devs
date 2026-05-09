"""TwinClient — cliente HTTP para o agent-twin-mcp-server.

Importado por outros MCPs para saber quem está operando na sessão atual
sem depender de Claude como intermediário. Fornece acesso a contexto
de autenticação, permissões e dados de usuário/tenant.

Uso:
    from shared.twin_client import TwinClient

    twin = TwinClient.from_env()
    user = twin.get_current_user()     # {"user_id": ..., "name": ..., "role": ...}
    ok   = twin.check_scope("deploy")  # True/False
    tenant = twin.get_tenant_id()      # "tenant_123" ou None
"""
from __future__ import annotations

import os
from typing import Any

from .base_client import BaseHTTPClient


class TwinClient(BaseHTTPClient):
    DEFAULT_TIMEOUT = 5.0

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7098",
        token: str = "",
        timeout: float | None = None,
        cache_ttl: float = 5.0,
    ) -> None:
        super().__init__(base_url=base_url, token=token, timeout=timeout, cache_ttl=cache_ttl)

    @classmethod
    def from_env(cls) -> TwinClient:
        port = int(os.getenv("TWIN_API_PORT", "7098"))
        token = os.getenv("TWIN_API_TOKEN", "")
        return cls(base_url=f"http://127.0.0.1:{port}", token=token)

    def is_authenticated(self) -> bool:
        """Verifica se há sessão ativa no agent-twin."""
        result = self._get("/session/user")
        return result is not None

    def get_current_user(self) -> dict[str, Any] | None:
        """Retorna dados do usuário autenticado ou None se sem sessão."""
        return self._get("/session/user")

    def get_session(self) -> dict[str, Any] | None:
        """Retorna sessão completa (usuário + contexto) ou None."""
        return self._get("/session")

    def get_context(self) -> dict[str, Any]:
        """Retorna contexto de ambiente ou {} se indisponível."""
        return self._get("/session/context") or {}

    def get_scopes(self) -> list[str]:
        """Retorna escopos do usuário atual ou [] se indisponível."""
        user = self._get("/session/user")
        return user.get("scopes", []) if user else []

    def check_scope(self, scope: str) -> bool:
        """Verifica se o usuário tem permissão para um escopo.

        check-scope retorna 403 quando negado — _post() retorna None para não-200.
        """
        result = self._post("/session/check-scope", {"scope": scope})
        return bool(result and result.get("allowed"))

    def get_environment(self) -> str | None:
        """Retorna o ambiente do usuário (dev/staging/production) ou None."""
        user = self.get_current_user()
        return user.get("environment") if user else None

    def get_tenant_id(self) -> str | None:
        """Retorna tenant_id da sessão (com cache 10s) ou None."""
        result = self._get_cached("/session/tenant", ttl=10.0)
        if result and result.get("has_tenant"):
            return result.get("tenant_id")
        return None
