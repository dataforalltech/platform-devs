"""Contrato do transporte HTTP do agregador — B04, B05 e B06 do BACKLOG.

Três defeitos que o transporte produzia sozinho, independentemente do que a tool
fizesse:

  * **B06** — `/mcp/tools/call` só checava a denylist. Qualquer nome que o dispatch
    de um domínio soubesse rotear EXECUTAVA, mesmo sem constar em
    `/mcp/tools/list` e portanto sem capability nem required_scope publicados para
    o gateway policiar.
  * **B04** — erro de execução voltava DENTRO do envelope de resultado normal, com
    HTTP 200 e sem `isError`. Para o gateway e para o agente consumidor isso é
    indistinguível de sucesso cujo retorno por acaso tem uma chave "error".
  * **B05** — `/v1/health/ready` compartilhava o handler de `/live` e devolvia 200
    sem tocar em nada. O orquestrador dava o serviço por pronto com o banco fora.

Nada aqui abre conexão real: as settings são um `SimpleNamespace` e a checagem da
fonte admin é substituída por dublê.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.server import mcp_server as M

_KEY = "unit-test-signing-key"
_TENANT = "tenant-a"


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        docs_enabled=False,
        mcp_context_signing_key=_KEY,
        mcp_twin_audience="mcp:devteam-mcp",
        url_admin_twin_jwks="",
        DB_ENGINE="mysql",
        DB_SSLMODE=None,
        DB_HEALTH_POOL_SIZE=2,
        ADMIN_DB_HOST="admin.invalid",
        ADMIN_DB_PORT=3306,
        ADMIN_DB_USER="u",
        ADMIN_DB_PASSWORD="p",  # noqa: S106 — valor de teste, sem I/O real
    )


def _meta() -> dict:
    """Monta um `_meta` com contexto assinado válido para `_TENANT`."""
    context = {
        "tenant_id": _TENANT,
        "policy_decision_id": "decision-1",
        "approval_ids": [],
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(_KEY.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return {
        "twin_token": "token-de-teste",
        "signed_context": encoded,
        "context_signature": signature,
        "policy_decision_id": "decision-1",
    }


@pytest.fixture()
def client(monkeypatch):
    """App com verificação de inner token substituída — o alvo aqui é o transporte."""
    monkeypatch.setattr(M, "_verify_inner_token", lambda _t, _s: {"tenant_id": _TENANT})
    return TestClient(M._build_http_app(_settings()))


def _call(client, name: str, arguments: dict | None = None):
    return client.post(
        "/mcp/tools/call",
        json={"params": {"name": name, "arguments": arguments or {}, "_meta": _meta()}},
    )


# ── B06: a superfície executável é a publicada ───────────────────────────────
def test_tool_fora_de_tool_schemas_nao_executa(client):
    """Nome desconhecido recusa ANTES do dispatch, com 404."""
    resp = _call(client, "dominio_inexistente_faz_alguma_coisa")
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_tool"


def test_denylist_continua_valendo_e_tem_precedencia(client):
    """Tool de segredo segue recusada com 403, não com 404."""
    resp = _call(client, "config_get_credential")
    assert resp.status_code == 403
    assert resp.json()["error"] == "tool_excluded"


def test_toda_tool_listada_esta_em_tool_schemas(client):
    """O gate de B06 não pode esconder nada do que é anunciado."""
    listadas = {t["name"] for t in client.get("/mcp/tools/list").json()["result"]["tools"]}
    assert listadas <= set(M._TOOL_SCHEMAS)
    assert not (listadas & M._EXCLUDE_TOOLS)


# ── B04: erro de execução chega como erro ────────────────────────────────────
def test_falha_de_execucao_devolve_500_e_isError(client, monkeypatch):
    async def _explode(*_a, **_kw):
        raise RuntimeError("falha interna qualquer")

    monkeypatch.setattr(M, "_run_tool", _explode)
    alvo = next(n for n in M._TOOL_SCHEMAS if n not in M._EXCLUDE_TOOLS)

    resp = _call(client, alvo)

    assert resp.status_code == 500
    body = resp.json()
    assert body["result"]["isError"] is True
    payload = json.loads(body["result"]["content"][0]["text"])
    assert payload["error"] == "internal_error"
    assert payload["tool"] == alvo


def test_sucesso_continua_sem_isError(client, monkeypatch):
    async def _ok(*_a, **_kw):
        return {"ok": True}

    monkeypatch.setattr(M, "_run_tool", _ok)
    alvo = next(n for n in M._TOOL_SCHEMAS if n not in M._EXCLUDE_TOOLS)

    resp = _call(client, alvo)

    assert resp.status_code == 200
    assert "isError" not in resp.json()["result"]


# ── B05: readiness verifica a fonte admin ────────────────────────────────────
def test_ready_devolve_503_quando_a_fonte_admin_nao_responde(client, monkeypatch):
    async def _down(_settings):
        raise ConnectionError("admin db fora")

    monkeypatch.setattr(M, "_check_admin_source", _down)

    resp = client.get("/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["reason"] == "admin_source_unreachable"


def test_ready_devolve_200_quando_a_fonte_admin_responde(client, monkeypatch):
    async def _up(_settings):
        return None

    monkeypatch.setattr(M, "_check_admin_source", _up)

    resp = client.get("/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_live_nao_depende_do_banco(client, monkeypatch):
    """Liveness afirma só que o processo respondeu — e não pode cair com o banco."""

    async def _down(_settings):
        raise ConnectionError("admin db fora")

    monkeypatch.setattr(M, "_check_admin_source", _down)

    for rota in ("/v1/health", "/v1/health/live"):
        resp = client.get(rota)
        assert resp.status_code == 200, rota
        assert resp.json()["status"] == "ok"
