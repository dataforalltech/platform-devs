"""Cliente S2S para mintar Twin Token no platform-admin (POST /api/v1/twin/sessions).

Usado pela PONTE do auth-mcp (AS OAuth): no `/oauth/token`, em vez de assinar um JWT
próprio, o AS troca a identidade autenticada por um **Twin Token** (aud=`mcp:gateway`)
emitido pelo `platform-admin` — o `access_token` que o cliente MCP (Claude Code) carrega
JÁ É um Twin Token válido para o gateway `platform-mcp`. Ver MCP_OAUTH_FRONTDOOR_DESIGN.md §2.2.

Contrato do admin (`app/modules/twin_session/routers.py`, POST `/api/v1/twin/sessions`):
  Headers: Authorization: Bearer <user JWT da plataforma>  (re-verificado; sub numérico)
           X-Tenant-Id                                      (casa com o claim do JWT)
           X-Internal-Token                                 (per-tenant, validado em PLATFORMS)
  Body:    {agentId, purposeId?, userId?, audiences?}       (audiences=["mcp:gateway"])
  201 →    {token, jti, scopes, expiresAt, twinId}

O `_transport` é injetável para teste unitário (sem HTTP real).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Sequence

# transport: (url, data_bytes, headers, timeout) -> (status_code, body_text)
Transport = Callable[[str, bytes, dict, float], "tuple[int, str]"]


class TwinSessionError(RuntimeError):
    """Falha ao mintar o Twin Token no admin (HTTP != 2xx, ou pré-condição da PONTE)."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"twin session mint failed (HTTP {status}): {body[:300]}")
        self.status = status
        self.body = body


def _http_post(url: str, data: bytes, headers: dict, timeout: float) -> "tuple[int, str]":
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URL interna controlada
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:  # 4xx/5xx do admin: propaga status+corpo
        return e.code, e.read().decode()


def mint_twin_session(
    *,
    admin_base_url: str,
    user_jwt: str,
    tenant_id: str,
    internal_token: str,
    agent_id: str,
    audiences: Sequence[str] | None = None,
    purpose_id: str | None = None,
    sessions_path: str = "/api/v1/twin/sessions",
    timeout: float = 10.0,
    _transport: Transport | None = None,
) -> dict[str, Any]:
    """Chama o admin e devolve a resposta parseada ({token, jti, scopes, expiresAt, twinId}).

    Levanta TwinSessionError em HTTP != 200/201.
    """
    url = admin_base_url.rstrip("/") + sessions_path
    body: dict[str, Any] = {"agentId": agent_id}
    if audiences:
        body["audiences"] = list(audiences)
    if purpose_id:
        body["purposeId"] = purpose_id
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {user_jwt}",
        "X-Tenant-Id": tenant_id,
        "X-Internal-Token": internal_token,
    }
    transport = _transport or _http_post
    status, text = transport(url, json.dumps(body).encode(), headers, timeout)
    if status not in (200, 201):
        raise TwinSessionError(status, text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise TwinSessionError(status, f"resposta não-JSON: {text[:200]}") from e
