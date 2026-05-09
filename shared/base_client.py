"""BaseHTTPClient — cliente HTTP base com cache TTL.

Classe base compartilhada para todos os MCPs que precisam se comunicar
com outros serviços via HTTP. Implementa cache simples em memória
com TTL (time-to-live) para otimizar buscas repetidas.

Uso:
    class MyClient(BaseHTTPClient):
        DEFAULT_TIMEOUT = 5.0
        ...
"""
from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)


class BaseHTTPClient:
    """Cliente HTTP com cache TTL simples para GET requests.

    Métodos:
    - _get(path): busca sem cache
    - _get_cached(path, ttl): busca com cache em dict (thread-tolerant)
    - _post(path, body): POST sem cache
    - is_available(): verifica se o serviço está acessível
    """

    DEFAULT_TIMEOUT = 5.0

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float | None = None,
        cache_ttl: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[Any, float]] = {}  # path → (result, cached_at)

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _get(self, path: str) -> Any | None:
        try:
            import httpx
            r = httpx.get(
                f"{self._base}/v1{path}",
                headers=self._headers(),
                timeout=self._timeout,
            )
            return r.json() if r.status_code == 200 else None
        except Exception as exc:  # noqa: BLE001
            _log.debug("http_client_unavailable path=%s: %s", path, exc)
            return None

    def _get_cached(self, path: str, ttl: float | None = None) -> Any | None:
        """GET com cache em memória (TTL em segundos).

        Múltiplas chamadas dentro do TTL retornam o resultado cacheado
        sem fazer nova requisição HTTP.
        """
        effective_ttl = ttl if ttl is not None else self._cache_ttl
        cached = self._cache.get(path)
        if cached is not None:
            result, cached_at = cached
            if (time.monotonic() - cached_at) < effective_ttl:
                return result
        result = self._get(path)
        self._cache[path] = (result, time.monotonic())
        return result

    def _post(self, path: str, body: dict) -> Any | None:
        try:
            import httpx
            r = httpx.post(
                f"{self._base}/v1{path}",
                headers=self._headers(),
                json=body,
                timeout=self._timeout,
            )
            return r.json() if r.status_code == 200 else None
        except Exception as exc:  # noqa: BLE001
            _log.debug("http_client_post_failed path=%s: %s", path, exc)
            return None

    def is_available(self) -> bool:
        """Verifica se o serviço está acessível."""
        result = self._get("/health")
        return result is not None and result.get("status") == "ok"
