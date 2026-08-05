"""Servidor MCP do devteam — sidecar kind=mcp_http, GATEWAY-READY (Model C) — AGREGADOR.

Consolida os ~20 backends DevTeam (personas + system) num único server: 1 image, 1
deploy, 1 audiência (``mcp:devteam-mcp``). Cada domínio é um sub-pacote em
`src/domains/<domain>/` que expõe um ``plugin.register()``; ESTE módulo é o boot/serve/
segurança COMPARTILHADO — idêntico ao dos servers-fonte (FastAPI + PEP inner-token +
stdio + tenant plumbing credencial-zero), apenas parametrizado pelos domínios ativos
(`src/domains/DOMAINS`). Ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md.

Implementa o contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome). As
     chaves de tool são ``<domain>_<op>`` (ex.: ``architecture_save_artifact``) — os
     nomes de op só precisam ser únicos DENTRO do domínio; o prefixo resolve as colisões
     entre domínios (ex.: ``save_artifact`` em vários personas).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:devteam-mcp) via JWKS
     do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O inner
     token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3).
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: cada domínio é stateful — "o agente gera o conteúdo, a tool persiste": as tools
persistem num MySQL via a Store do domínio (tenant-scoped, dual-db, credencial-zero).
Todos os domínios coexistem no schema do tenant (1 pool por tenant). Não há backend REST
intermediário; o dispatcher abre a sessão do tenant e cada domínio recebe a sua Store
ligada a ela.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool
from platform_database import close_health_pool, close_tenant_pools, init_health_pool
from platform_database.orm import configure, for_tenant
from platform_database.orm.dialects import dialect_for_pool
from platform_database.tenant_resolver import get_pool_for_tenant

from ..config.logging import configure_logging
from ..config.settings import DevteamSettings, get_settings
from ..domains import DOMAINS

_log = logging.getLogger(__name__)

# ── Agregação dos domínios ────────────────────────────────────────────────────
# Índice domínio → dict de register() (para o roteamento por prefixo do _dispatch).
_DOMAINS_BY_KEY: dict[str, dict[str, Any]] = {d["name"]: d for d in DOMAINS}

# _TOOL_SCHEMAS = merge dos schemas de todos os domínios. As chaves já vêm prefixadas
# (``<domain>_<op>``) do plugin.register(), então NÃO há colisão entre domínios.
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {}
for _domain in DOMAINS:
    _TOOL_SCHEMAS.update(_domain["schemas"])

# devteam-mcp não expõe tool tokenless: TODAS as tools tocam estado do tenant e exigem
# inner token válido (fail-closed). O liveness fica no /v1/health (sem tool).
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
_EXCLUDE_TOOLS: frozenset[str] = frozenset(
    {
        "infra_get_lease_ssh_key",
        "config_get_credential",
        "config_set_credential",
        "config_set_credential_secure",
        "config_read_env_file",
        "services_read_env_file",
    }
)

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: DevteamSettings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:devteam-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:devteam-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


def _verify_signed_context(
    meta: dict[str, Any], settings: DevteamSettings, tenant_id: str
) -> dict[str, Any]:
    """Validate the gateway context and return only trusted policy metadata."""
    encoded = meta.get("signed_context")
    signature = meta.get("context_signature")
    if not isinstance(encoded, str) or not isinstance(signature, str):
        raise PermissionError("missing signed gateway context")
    expected = hmac.new(
        settings.mcp_context_signing_key.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("invalid gateway context signature")
    padding = "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
    if payload.get("tenant_id") != tenant_id:
        raise PermissionError("gateway context tenant mismatch")
    decision_id = payload.get("policy_decision_id")
    if not isinstance(decision_id, str) or not decision_id:
        raise PermissionError("missing verified policy decision")
    if decision_id != meta.get("policy_decision_id"):
        raise PermissionError("policy decision mismatch")
    return payload


# ── Dispatcher (roteia por prefixo de domínio; abre a Store do domínio na sessão) ──


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Descobre o domínio pelo prefixo ``<domain>_`` e delega ao dispatch do domínio.

    O tenant NÃO viaja nos args (INV-3): a ``session`` já está ligada ao pool do tenant
    (resolvido dos claims do inner token). O ``dispatch`` do domínio recebe a SESSÃO e
    constrói sua(s) própria(s) Store(s) sobre ela — contrato uniforme p/ domínios
    single-store (ex.: architecture) e multi-store (ex.: ai-governance)."""
    # Roteia casando a MAIOR chave <key> tal que name == "<key>_..." (longest-prefix).
    # Robusto a domínios com '-' ou '_' (ex.: product-owner, ai-governance, dev-twin) —
    # um split no 1º '_' quebraria esses silenciosamente.
    matched = [k for k in _DOMAINS_BY_KEY if name.startswith(f"{k}_")]
    if not matched:
        raise KeyError(name)
    domain = _DOMAINS_BY_KEY[max(matched, key=len)]
    return await domain["dispatch"](name, args, session)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: DevteamSettings, tenant_id: str) -> None:
    """Garante as tabelas de TODOS os domínios no banco do tenant (uma vez por processo).

    O engine é o do dialeto do pool resolvido — é o ponto que faz o mesmo código servir
    o dual-db. Todas as tabelas dos domínios ativos coexistem no schema do tenant."""
    if tenant_id in _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if tenant_id in _SCHEMA_READY:
            return
        # Mesmo pool cacheado que o for_tenant usará (registry por TenantDBConfig).
        pool = await get_pool_for_tenant(settings, tenant_id, strict=True)
        engine = dialect_for_pool(pool).name
        for domain in DOMAINS:
            await domain["ensure_schema"](pool, engine=engine)
        _SCHEMA_READY.add(tenant_id)


async def _run_tool(
    name: str, arguments: dict[str, Any], settings: DevteamSettings, tenant_id: str
) -> dict[str, Any]:
    """Abre a sessão tenant-scoped (credencial-zero), garante o schema e despacha."""
    await _ensure_tenant_schema(settings, tenant_id)
    async with for_tenant(tenant_id) as session:
        return await _dispatch(name, arguments, session)


class _AdminHealthSettings:
    """Adapta ``ADMIN_DB_*`` ao protocolo ``DBSettings`` do pool de health.

    O pool de health da lib lê os nomes ``DB_*``; aqui eles apontam para a conexão
    ADMIN, que é quem resolve a credencial de cada tenant em
    ``ADMIN_DATAFORALL.PLATFORMS``. É a dependência sem a qual nenhuma tool
    funciona — e portanto a que readiness precisa provar.
    """

    def __init__(self, settings: DevteamSettings) -> None:
        self.DB_ENGINE = settings.DB_ENGINE
        self.DB_HOST = settings.ADMIN_DB_HOST
        self.DB_PORT = settings.ADMIN_DB_PORT
        self.DB_NAME = "ADMIN_DATAFORALL"
        self.DB_USER = settings.ADMIN_DB_USER
        self.DB_PASSWORD = settings.ADMIN_DB_PASSWORD
        self.DB_SSLMODE = settings.DB_SSLMODE
        self.DB_HEALTH_POOL_SIZE = settings.DB_HEALTH_POOL_SIZE


async def _check_admin_source(settings: DevteamSettings) -> None:
    """``SELECT 1`` na fonte admin. Levanta se ela não responder.

    Usa o pool dedicado de health da lib (1-2 conexões, timeout de 2s) para que o
    probe não falhe quando o pool principal estiver saturado — o que mataria o
    container justamente no pior momento. ``init_health_pool`` é idempotente.
    """
    pool = await init_health_pool(_AdminHealthSettings(settings))  # type: ignore[arg-type]
    await pool.fetchval("SELECT 1")


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: DevteamSettings) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto a store: cada chamada abre uma sessão tenant-scoped
    (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="devteam-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    @app.get("/v1/health/live")
    def health() -> dict[str, Any]:
        """Liveness: o processo respondeu. Não afirma nada sobre dependências."""
        return {
            "status": "ok",
            "service": "devteam-mcp",
            "tools": len(_TOOL_SCHEMAS) - len(_EXCLUDE_TOOLS),
        }

    @app.get("/v1/health/ready")
    async def health_ready() -> Any:
        """Readiness: a conexão admin responde?

        Antes, `/ready` compartilhava o handler de `/live` e devolvia 200 sem tocar
        em nada. O orquestrador dava o serviço por pronto com o banco fora, e a
        falha aparecia só na primeira chamada de tool, dentro de
        `_ensure_tenant_schema`. Readiness que não verifica dependência é liveness
        com outro nome.

        A verificação é a resolução da fonte admin (ADMIN_DB_*) — é dela que sai a
        credencial de cada tenant no modelo credencial-zero, então sem ela nenhuma
        tool funciona. Não se abre pool por tenant aqui: o tenant vem dos claims de
        cada requisição, e o probe não tem nenhum.
        """
        base = {
            "service": "devteam-mcp",
            "tools": len(_TOOL_SCHEMAS) - len(_EXCLUDE_TOOLS),
        }
        try:
            await _check_admin_source(settings)
        except Exception as exc:  # noqa: BLE001 — readiness falha fechada
            _log.warning("readiness_failed detail=%s", type(exc).__name__)
            return JSONResponse(
                status_code=503,
                content={**base, "status": "unavailable", "reason": "admin_source_unreachable"},
            )
        return {**base, "status": "ok"}

    @app.get("/mcp/tools/list")
    def http_list_tools() -> dict:
        tools = []
        for name, meta in _TOOL_SCHEMAS.items():
            if name in _EXCLUDE_TOOLS:
                continue
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            }
            entry.update({f: meta[f] for f in _POLICY_FIELDS})
            tools.append(entry)
        return {"result": {"tools": tools}}

    @app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # A superfície executável é a PUBLICADA, e nada além dela. Sem esta
        # checagem, qualquer nome que o dispatch de um domínio saiba rotear
        # executava — mesmo sem constar em /mcp/tools/list e, portanto, sem
        # capability nem required_scope publicados para o gateway policiar.
        # É o que separava as tools listadas das despachaveis.
        if name not in _TOOL_SCHEMAS:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})

        # Toda tool do devteam toca estado do tenant → inner token obrigatório (não há
        # _EXEMPT_TOOLS). O tenant vem SEMPRE dos claims (SEC-035 / INV-3), nunca do arg.
        twin_token = (params.get("_meta") or {}).get("twin_token")
        if not twin_token:
            return JSONResponse(status_code=401, content={"error": "missing_twin_token"})
        try:
            claims = _verify_inner_token(twin_token, settings)
        except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha de verificação
            _log.warning("inner_token_rejected tool=%s detail=%s", name, exc)
            return JSONResponse(status_code=401, content={"error": "invalid_twin_token"})
        tenant_id = claims.get("tenant_id")
        if not tenant_id:
            return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})
        try:
            trusted_context = _verify_signed_context(
                params.get("_meta") or {}, settings, str(tenant_id)
            )
        except Exception as exc:  # noqa: BLE001 - any verification failure denies execution
            _log.warning("gateway_context_rejected tool=%s detail=%s", name, exc)
            return JSONResponse(status_code=401, content={"error": "invalid_gateway_context"})
        arguments["_verified_approval_ids"] = list(
            trusted_context.get("approval_ids") or []
        )

        try:
            payload = await _run_tool(name, arguments, settings, str(tenant_id))
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception:  # noqa: BLE001 — resposta genérica; detalhe fica apenas no log
            # Falha de execução é ERRO, e precisa chegar como erro. Antes, o
            # payload de erro ia dentro do envelope de resultado normal, com HTTP
            # 200 e sem `isError` — para o gateway e para o agente consumidor isso
            # é indistinguível de uma execução bem-sucedida cujo retorno por acaso
            # tem uma chave "error". É a mesma classe de problema dos stubs que
            # mentem, só que produzida pelo transporte.
            _log.exception("tool_internal_error: %s", name)
            erro = [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": "internal_error", "tool": name}, ensure_ascii=False, indent=2
                    ),
                )
            ]
            return JSONResponse(
                status_code=500,
                content={
                    "result": {
                        "content": [c.model_dump(exclude_none=True) for c in erro],
                        "isError": True,
                    }
                },
            )
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    @app.on_event("shutdown")
    async def _close_pools() -> None:
        # Fecha os pools por-tenant no shutdown (registry compartilhado da lib).
        await close_tenant_pools()
        # O pool de health é separado e tem ciclo de vida próprio.
        await close_health_pool()

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def build_server() -> tuple[Any, DevteamSettings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    A persistência é tenant-scoped e resolvida por-request (credencial-zero).
    ``orm.configure(settings)`` registra a fonte admin (ADMIN_DB_*) usada para
    resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()  # fail-fast STD-SEC-001/004/006
    configure_logging(settings)  # logging estruturado JSON (STD-OBS-001)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant
    http_app = _build_http_app(settings)
    _log.info(
        "devteam_mcp_ready tools=%d domains=%d engine=%s",
        len(_TOOL_SCHEMAS),
        len(DOMAINS),
        settings.DB_ENGINE,
    )

    server: Server = Server("devteam-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
            if name not in _EXCLUDE_TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # O transporte stdio não carrega o inner token (logo, sem tenant). devteam-mcp
        # é gateway-only: a execução real entra pelo sidecar HTTP (/mcp/tools/call), onde
        # o tenant vem dos claims verificados. Aqui recusamos fail-closed (sem tenant).
        if name not in _TOOL_SCHEMAS:
            payload: dict[str, Any] = {"error": "unknown_tool", "tool": name}
        else:
            payload = {
                "error": "tenant_context_required",
                "tool": name,
                "detail": (
                    "devteam-mcp é tenant-scoped e gateway-only; chame via o sidecar HTTP "
                    "(/mcp/tools/call) com o inner Twin Token — o tenant vem dos claims."
                ),
            }
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, http_app = build_server()
    cfg = uvicorn.Config(
        http_app,
        host="0.0.0.0",  # noqa: S104 — bind interno do container; ingress só via gateway (INV-1)
        port=settings.mcp_port,
        log_level="warning",
        access_log=False,
    )
    server_http = uvicorn.Server(cfg)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await asyncio.gather(
                server.run(read_stream, write_stream, server.create_initialization_options()),
                server_http.serve(),
            )
    except (EOFError, BrokenPipeError):
        pass


def main() -> None:
    # MCP_HTTP_ONLY=1 → só o sidecar HTTP (uso típico atrás do gateway, sem stdio).
    if os.getenv("MCP_HTTP_ONLY", "0") == "1":
        import uvicorn

        _server, settings, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
