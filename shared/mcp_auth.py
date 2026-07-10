"""Biblioteca de autenticação/autorização compartilhada para MCPs da plataforma.

Implementa o padrão definido em MCP_SERVICE_STANDARD.md:

- Emissão de JWT (RS256) com claims iss/aud/sub/scope/exp/jti  → usado pelo auth-mcp (AS)
- Validação de JWT (assinatura via JWKS/chave pública, aud, exp, iss, scope) → usado por todo MCP
- Store de token estático (bcrypt) para o bootstrap (Bearer opaco por usuário)
- Middleware Bearer (Starlette) que protege /mcp: 401 + WWW-Authenticate com resource_metadata
- Protected Resource Metadata (RFC 9728) helper

Regras de ouro aplicadas:
- Valida SEMPRE o audience (evita reuso de token entre serviços).
- Nunca repassa o token do usuário downstream (o edge deriva identidade; ver assertion interna).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import bcrypt
import jwt
from jwt import PyJWK, PyJWKClient
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

# ============================================================================
# Principal (identidade autenticada)
# ============================================================================

@dataclass
class Principal:
    """Identidade resolvida a partir de um token validado."""
    subject: str
    scopes: list[str] = field(default_factory=list)
    role: str = "user"
    tenant_id: str = "default"
    token_type: str = "bearer"  # "jwt" | "static"
    raw_claims: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, required: str | None) -> bool:
        if not required:
            return True
        if "*" in self.scopes:
            return True
        # escopo hierárquico: "security:*" concede "security:scan"
        prefix = required.split(":", 1)[0]
        return required in self.scopes or f"{prefix}:*" in self.scopes


class AuthError(Exception):
    def __init__(self, status: int, error: str, description: str = ""):
        self.status = status
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}")


# ============================================================================
# Emissão de JWT (Authorization Server)
# ============================================================================

def issue_jwt(
    *,
    private_key_pem: str,
    kid: str,
    issuer: str,
    subject: str,
    audience: str | list[str],
    scopes: Iterable[str],
    ttl_seconds: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Emite um access token JWT (RS256) com os claims exigidos pela spec MCP/OAuth."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "jti": _new_jti(now, subject),
        "scope": " ".join(scopes),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers={"kid": kid})


def _new_jti(now: int, subject: str) -> str:
    # jti único sem depender de random proibido no harness; base em contador temporal + sujeito
    return f"{subject}-{now}-{now % 100000}"


# ============================================================================
# Validação de JWT (Resource Server)
# ============================================================================

class JwtValidator:
    """Valida access tokens JWT emitidos pelo Authorization Server.

    Usa JWKS remoto (produção) ou uma chave pública/JWK local (teste/bootstrap).
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        public_key_pem: str | None = None,
        jwk: dict[str, Any] | None = None,
        leeway: int = 30,
    ):
        self.issuer = issuer
        self.audience = audience
        self.leeway = leeway
        self._jwks_client = PyJWKClient(jwks_url) if jwks_url else None
        self._public_key_pem = public_key_pem
        self._jwk = jwk

    def _signing_key(self, token: str):
        if self._jwks_client is not None:
            return self._jwks_client.get_signing_key_from_jwt(token).key
        if self._jwk is not None:
            return PyJWK.from_dict(self._jwk).key
        if self._public_key_pem is not None:
            return self._public_key_pem
        raise AuthError(500, "server_error", "validator sem chave configurada")

    def validate(self, token: str) -> Principal:
        try:
            key = self._signing_key(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise AuthError(401, "invalid_token", "token expirado")
        except jwt.InvalidAudienceError:
            raise AuthError(401, "invalid_token", "audience inválido para este recurso")
        except jwt.PyJWTError as e:
            raise AuthError(401, "invalid_token", f"token inválido: {e}")

        scope_str = claims.get("scope", "")
        scopes = scope_str.split() if isinstance(scope_str, str) else list(scope_str)
        return Principal(
            subject=claims["sub"],
            scopes=scopes,
            role=claims.get("role", "user"),
            tenant_id=claims.get("tenant_id", "default"),
            token_type="jwt",
            raw_claims=claims,
        )


# ============================================================================
# Store de token estático (bootstrap) — Bearer opaco com hash bcrypt
# ============================================================================

@dataclass
class StaticToken:
    token_hash: bytes          # bcrypt hash do token opaco
    subject: str
    scopes: list[str]
    role: str = "developer"
    tenant_id: str = "default"
    expires_at: int | None = None
    revoked: bool = False


class StaticTokenStore:
    """Validador de tokens estáticos por usuário (substitui os test-token hardcoded).

    Em produção, `records` vem de uma tabela agent_tokens no Postgres. Aqui a interface
    é a mesma; injete os registros de onde quiser.
    """

    def __init__(self, records: list[StaticToken] | None = None):
        self.records = records or []

    @staticmethod
    def hash_token(raw: str) -> bytes:
        return bcrypt.hashpw(raw.encode(), bcrypt.gensalt())

    def validate(self, raw_token: str) -> Principal:
        now = int(time.time())
        raw = raw_token.encode()
        for rec in self.records:
            if rec.revoked:
                continue
            if rec.expires_at and now >= rec.expires_at:
                continue
            if bcrypt.checkpw(raw, rec.token_hash):
                return Principal(
                    subject=rec.subject,
                    scopes=list(rec.scopes),
                    role=rec.role,
                    tenant_id=rec.tenant_id,
                    token_type="static",
                )
        raise AuthError(401, "invalid_token", "token estático inválido/expirado/revogado")


# ============================================================================
# Protected Resource Metadata (RFC 9728)
# ============================================================================

def protected_resource_metadata(*, resource: str, authorization_servers: list[str], scopes: list[str]) -> dict[str, Any]:
    """Corpo do /.well-known/oauth-protected-resource que dispara o fluxo OAuth do cliente."""
    return {
        "resource": resource,
        "authorization_servers": authorization_servers,
        "scopes_supported": scopes,
        "bearer_methods_supported": ["header"],
    }


# ============================================================================
# Middleware Bearer para servidores MCP (Starlette/ASGI)
# ============================================================================

class BearerAuthMiddleware:
    """Protege os paths do MCP exigindo Bearer válido; injeta request.state.principal.

    - Paths públicos (health, .well-known) passam sem token.
    - Sem/È token inválido → 401 com WWW-Authenticate apontando o resource_metadata.
    - Se `scope_for_request` for fornecido, aplica autorização por ferramenta (least privilege):
      recebe (method, tool_name) e devolve o scope mínimo exigido; 403 se faltar.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_metadata_url: str,
        validators: list[Callable[[str], Principal]],
        public_paths: Iterable[str] = ("/v1/health", "/health", "/.well-known/"),
        protected_prefix: str = "/mcp",
        scope_for_request: Callable[[str, str | None], str | None] | None = None,
    ):
        self.app = app
        self.resource_metadata_url = resource_metadata_url
        self.validators = validators
        self.public_paths = tuple(public_paths)
        self.protected_prefix = protected_prefix
        self.scope_for_request = scope_for_request

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if self._is_public(path) or not path.startswith(self.protected_prefix):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        auth_header = request.headers.get("authorization")

        try:
            # Autenticação pode fazer I/O BLOQUEANTE (fetch de JWKS, bcrypt). Rodar no
            # event loop travaria os streams concorrentes (POST + GET SSE) do Streamable
            # HTTP e causaria deadlock com clientes reais. Por isso vai para um thread.
            import anyio
            principal = await anyio.to_thread.run_sync(self._authenticate, auth_header)
        except AuthError as e:
            await self._challenge(send, e)
            return

        # Autorização por ferramenta (least privilege) — precisa espiar o corpo JSON-RPC.
        if self.scope_for_request is not None and scope["method"] == "POST":
            body = await request.body()
            required = self._required_scope(body)
            if not principal.has_scope(required):
                await self._forbidden(send, required)
                return
            # reinjeta o corpo consumido para o app downstream, delegando eventos
            # subsequentes ao receive ORIGINAL (senão o SSE aborta achando que o
            # cliente desconectou)
            receive = _replay_receive(body, receive)

        scope["state"] = scope.get("state", {})
        scope["state"]["principal"] = principal
        await self.app(scope, receive, send)

    def _authenticate(self, auth_header: str | None) -> Principal:
        if not auth_header or not auth_header.startswith("Bearer "):
            raise AuthError(401, "invalid_request", "Authorization Bearer ausente")
        token = auth_header[7:].strip()
        last: AuthError | None = None
        for validator in self.validators:
            try:
                return validator(token)
            except AuthError as e:
                last = e
        raise last or AuthError(401, "invalid_token", "token não validável")

    def _required_scope(self, body: bytes) -> str | None:
        try:
            msg = json.loads(body or b"{}")
        except (json.JSONDecodeError, ValueError):
            return None
        method = msg.get("method", "")
        tool = (msg.get("params") or {}).get("name")
        return self.scope_for_request(method, tool) if self.scope_for_request else None

    def _is_public(self, path: str) -> bool:
        return any(path == p or path.startswith(p) for p in self.public_paths)

    async def _challenge(self, send: Send, err: AuthError) -> None:
        www = (
            f'Bearer resource_metadata="{self.resource_metadata_url}", '
            f'error="{err.error}", error_description="{err.description}"'
        )
        resp = JSONResponse(
            {"error": err.error, "error_description": err.description},
            status_code=err.status,
            headers={"WWW-Authenticate": www},
        )
        await resp(_dummy_scope(), _noop_receive, send)

    async def _forbidden(self, send: Send, required: str | None) -> None:
        resp = JSONResponse(
            {"error": "insufficient_scope", "error_description": f"scope requerido: {required}"},
            status_code=403,
            headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{required}"'},
        )
        await resp(_dummy_scope(), _noop_receive, send)


def mount_lowlevel_streamable_http(
    server: Any,
    *,
    resource: str,
    prm_url: str,
    as_issuer: str,
    as_jwks_url: str,
    scopes_supported: list[str],
    scope_for_tool: dict[str, str] | Callable[[str], str | None],
    validators: list[Callable[[str], Principal]] | None = None,
    stateless: bool = False,
):
    """Expõe um `mcp.server.Server` de baixo nível via Streamable HTTP + auth.

    Para MCPs legados cujas ferramentas têm injeção de dependência (store/settings) e
    despacho próprio: preserva o `Server` e seu dispatch, só troca o transporte para
    Streamable HTTP (SDK) e adiciona o BearerAuthMiddleware com escopo por ferramenta.

    `scope_for_tool`: dict {tool_name: scope} ou callable(tool_name)->scope|None.
    Retorna um app ASGI pronto para uvicorn (já embrulhado no middleware Bearer).
    """
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    manager = StreamableHTTPSessionManager(app=server, stateless=stateless)

    async def _mcp_asgi(scope, receive, send):
        # handler ASGI que delega ao session manager (equivalente ao StreamableHTTPASGIApp)
        await manager.handle_request(scope, receive, send)

    async def health(_req: Request):
        return JSONResponse({"status": "ok", "server": getattr(server, "name", "mcp")})

    async def prm(_req: Request):
        return JSONResponse(protected_resource_metadata(
            resource=resource, authorization_servers=[as_issuer], scopes=scopes_supported))

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    star = Starlette(
        routes=[
            Route("/v1/health", health, methods=["GET"]),
            Route("/.well-known/oauth-protected-resource", prm, methods=["GET"]),
            Mount("/mcp", app=_mcp_asgi),
        ],
        lifespan=lifespan,
    )

    if validators is None:
        validators = [JwtValidator(issuer=as_issuer, audience=resource, jwks_url=as_jwks_url).validate]

    if isinstance(scope_for_tool, dict):
        _map = scope_for_tool

        def _resolve(tool: str) -> str | None:
            return _map.get(tool, "")  # "" → autenticado mas sem escopo específico
    else:
        _resolve = scope_for_tool

    def scope_for_request(method: str, tool: str | None) -> str | None:
        if method != "tools/call" or not tool:
            return None
        return _resolve(tool)

    return BearerAuthMiddleware(
        star,
        resource_metadata_url=prm_url,
        validators=validators,
        scope_for_request=scope_for_request,
    )


def _replay_receive(body: bytes, original: Receive) -> Receive:
    """Reentrega o corpo já lido uma vez; depois delega ao receive original.

    Delegar (em vez de forjar http.disconnect) é essencial para respostas SSE de
    longa duração: o app monitora o receive para saber quando o cliente desconecta;
    um disconnect forjado abortaria o stream ("ASGI returned without completing").
    """
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await original()

    return receive


def _dummy_scope() -> Scope:
    return {"type": "http", "headers": []}


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}
