#!/usr/bin/env python3
"""auth-mcp — Authorization Server (OAuth 2.1) da plataforma.

Conforme MCP_SERVICE_STANDARD.md §6. Endpoints:

  Discovery
    GET  /.well-known/jwks.json                  → chaves públicas (JWKS)
    GET  /.well-known/oauth-authorization-server → metadata do AS (RFC 8414)

  Registro dinâmico (Claude Code registra sozinho)
    POST /register                               → Dynamic Client Registration (RFC 7591)

  Fluxo interativo (login de browser do Claude Code)
    GET  /oauth/authorize                        → tela de consentimento
    POST /oauth/authorize                        → aprova → emite authorization code
    POST /oauth/token (authorization_code)       → troca code+PKCE por access+refresh token
    POST /oauth/token (refresh_token)            → rotaciona refresh e emite novo access

  Serviço↔serviço / bootstrap
    POST /oauth/token (client_credentials)       → access token direto

    POST /oauth/introspect                       → RFC 7662
    GET  /v1/health

Segurança: PKCE S256 obrigatório p/ authorization_code; access token JWT RS256 com
aud = resource (RFC 8707); refresh token single-use (rotação); chave via secrets.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import os
import secrets
import sys
import time
from urllib.parse import urlencode

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.mcp_auth import issue_jwt  # noqa: E402
from shared.oauth_store import OAuthClient, make_store  # noqa: E402
from shared.user_store import make_user_store  # noqa: E402
from oidc_upstream import UpstreamOIDC, OIDCError  # noqa: E402

ISSUER = os.getenv("AS_ISSUER", "http://localhost:7103")
KID = os.getenv("AS_KID", "auth-mcp-key-1")
DEFAULT_TTL = int(os.getenv("AS_TOKEN_TTL", "3600"))
CODE_TTL = int(os.getenv("AS_CODE_TTL", "300"))
REFRESH_TTL = int(os.getenv("AS_REFRESH_TTL", str(30 * 24 * 3600)))

SUPPORTED_SCOPES = [
    "security:read", "security:scan", "security:model", "security:*",
    "qa-engineer:*", "backend:*", "offline_access",
]

STORE = make_store()
USER_STORE = make_user_store()
UPSTREAM = UpstreamOIDC.from_env()  # federação SSO opcional (config-gated)


# ============================================================================
# Chave de assinatura (secrets manager / arquivo / env)  [task: gestão de chave]
# ============================================================================

def _load_or_generate_key() -> tuple[str, str, dict]:
    """Retorna (private_pem, public_pem, public_jwk).

    Ordem de resolução:
      1. AS_PRIVATE_KEY_FILE  → caminho de um PEM (volume/secret montado)
      2. AS_PRIVATE_KEY_PEM   → PEM inline (secrets manager → env)
      3. dev fallback         → chave EFÊMERA (com aviso; tokens morrem a cada restart)
    """
    pem: str | None = None
    key_file = os.getenv("AS_PRIVATE_KEY_FILE")
    if key_file and os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            pem = f.read()
    else:
        pem = os.getenv("AS_PRIVATE_KEY_PEM")

    if pem:
        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    else:
        print("⚠️  Sem AS_PRIVATE_KEY_FILE/PEM — gerando chave EFÊMERA (só dev).", file=sys.stderr)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return private_pem, public_pem, jwk


PRIVATE_PEM, PUBLIC_PEM, PUBLIC_JWK = _load_or_generate_key()


# ============================================================================
# Seed de clients de serviço (client_credentials / bootstrap)
# ============================================================================

def _seed_service_clients() -> None:
    raw = os.getenv("AS_CLIENTS_JSON")
    if raw:
        for cid, c in json.loads(raw).items():
            secret_hash = c.get("secret_hash")
            if isinstance(secret_hash, str):
                secret_hash = secret_hash.encode()
            STORE.create_client(OAuthClient(
                client_id=cid,
                client_secret_hash=secret_hash,
                redirect_uris=c.get("redirect_uris", []),
                scopes=c.get("scopes", []),
                grant_types=c.get("grant_types", ["client_credentials"]),
                token_endpoint_auth_method="client_secret_post",
                subject=c.get("subject", f"svc:{cid}"),
                client_name=c.get("client_name", cid),
            ))
        return
    print("⚠️  Sem AS_CLIENTS_JSON — criando client de DEMO 'security-dev'.", file=sys.stderr)
    demo_secret = os.getenv("AS_DEMO_SECRET", "dev-secret-change-me")
    # DEV: escopos de TODOS os DevTeam, para o mesmo client emitir tokens de teste
    # para qualquer DevTeam via client_credentials. Só vale quando AS_CLIENTS_JSON está vazio.
    STORE.create_client(OAuthClient(
        client_id="security-dev",
        client_secret_hash=bcrypt.hashpw(demo_secret.encode(), bcrypt.gensalt()),
        redirect_uris=[],
        scopes=["security:*", "qa-engineer:*", "architecture:*", "backend:*",
                "frontend:*", "devops:*", "product-owner:*", "product-manager:*"],
        grant_types=["client_credentials"],
        token_endpoint_auth_method="client_secret_post",
        subject="svc:security-dev",
        client_name="MCP Dev (bootstrap, todos os DevTeam)",
    ))


_seed_service_clients()

app = FastAPI(title="auth-mcp Authorization Server", version="2.0.0")


# ============================================================================
# Helpers
# ============================================================================

def _authorized_scopes(requested: str, allowed: list[str]) -> list[str]:
    if not requested:
        return list(allowed)
    granted = []
    for s in requested.split():
        prefix = s.split(":", 1)[0]
        if s in allowed or f"{prefix}:*" in allowed or s == "offline_access":
            granted.append(s)
    return granted


def _b64url_sha256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _mint_access(subject: str, resource: str, scopes: list[str], tenant_id: str,
                 client_id: str, role: str = "user") -> str:
    return issue_jwt(
        private_key_pem=PRIVATE_PEM, kid=KID, issuer=ISSUER, subject=subject,
        audience=resource, scopes=scopes, ttl_seconds=DEFAULT_TTL,
        extra_claims={"tenant_id": tenant_id, "client_id": client_id, "role": role},
    )


def _gen_pkce() -> tuple[str, str]:
    """Gera (code_verifier, code_challenge S256) para a perna auth-mcp→IdP."""
    verifier = secrets.token_urlsafe(48)
    return verifier, _b64url_sha256(verifier)


# ============================================================================
# Discovery
# ============================================================================

@app.get("/.well-known/jwks.json")
async def jwks():
    return {"keys": [PUBLIC_JWK]}


@app.get("/.well-known/oauth-authorization-server")
async def as_metadata():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "introspection_endpoint": f"{ISSUER}/oauth/introspect",
        "registration_endpoint": f"{ISSUER}/register",
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": SUPPORTED_SCOPES,
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
    }


# ============================================================================
# Dynamic Client Registration (RFC 7591)
# ============================================================================

@app.post("/register")
async def register(request: Request):
    body = await request.json()
    redirect_uris = body.get("redirect_uris", [])
    auth_method = body.get("token_endpoint_auth_method", "none")
    grant_types = body.get("grant_types", ["authorization_code", "refresh_token"])
    scope = body.get("scope", "security:read")

    client_id = f"dcr-{secrets.token_urlsafe(12)}"
    client_secret = None
    secret_hash = None
    if auth_method != "none":
        client_secret = secrets.token_urlsafe(32)
        secret_hash = bcrypt.hashpw(client_secret.encode(), bcrypt.gensalt())

    STORE.create_client(OAuthClient(
        client_id=client_id,
        client_secret_hash=secret_hash,
        redirect_uris=redirect_uris,
        scopes=scope.split(),
        grant_types=grant_types,
        token_endpoint_auth_method=auth_method,
        client_name=body.get("client_name", ""),
    ))
    resp: dict = {
        "client_id": client_id,
        "redirect_uris": redirect_uris,
        "grant_types": grant_types,
        "token_endpoint_auth_method": auth_method,
        "scope": scope,
    }
    if client_secret:
        resp["client_secret"] = client_secret
    return JSONResponse(resp, status_code=201)


# ============================================================================
# Authorization endpoint (consent + code)
# ============================================================================

def _render_login_consent(fields: dict, granted: list[str], client, error: str = "") -> str:
    """Renderiza a tela de LOGIN + CONSENT. `fields` são reenviados como hidden inputs."""
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in fields.items()
    )
    err_html = (f'<p style="background:#fde;color:#900;padding:8px;border-radius:4px">'
                f'{html.escape(error)}</p>') if error else ""
    sso_html = ""
    if UPSTREAM.enabled:
        sso_html = (f'<p><a href="/oauth/sso/start?rid={html.escape(fields.get("_rid",""))}" '
                    f'style="display:inline-block;padding:8px 16px;background:#036;color:#fff;'
                    f'text-decoration:none;border-radius:4px">Entrar via SSO ({html.escape(UPSTREAM.name)})</a></p>'
                    f'<hr><p style="color:#666">ou entre com usuário e senha:</p>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Autorizar acesso</title></head>
<body style="font-family:system-ui;max-width:480px;margin:60px auto">
<h2>🛡️ auth-mcp — Autorização</h2>
<p><b>{html.escape(client.client_name or fields.get("client_id",""))}</b> quer acessar
<code>{html.escape(fields.get("resource",""))}</code> com os escopos:</p>
<ul>{"".join(f"<li><code>{html.escape(s)}</code></li>" for s in granted)}</ul>
{err_html}{sso_html}
<form method="post" action="/oauth/authorize">{hidden}
<p>Usuário:<br><input name="username" required autofocus></p>
<p>Senha:<br><input name="password" type="password" required></p>
<button name="decision" value="approve" style="padding:8px 16px">Entrar e aprovar</button>
<button name="decision" value="deny" style="padding:8px 16px">Negar</button>
</form></body></html>"""


@app.get("/oauth/authorize")
async def authorize_get(
    response_type: str, client_id: str, redirect_uri: str,
    code_challenge: str, code_challenge_method: str = "S256",
    scope: str = "", state: str = "", resource: str = "",
):
    if response_type != "code":
        raise HTTPException(400, "unsupported_response_type")
    if code_challenge_method != "S256":
        raise HTTPException(400, "code_challenge_method deve ser S256")
    client = STORE.get_client(client_id)
    if not client:
        raise HTTPException(400, "invalid_client")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "redirect_uri não registrado para o client")
    if not resource:
        raise HTTPException(400, "invalid_target: resource (RFC 8707) é obrigatório")

    granted = _authorized_scopes(scope, client.scopes)
    rid = ""
    if UPSTREAM.enabled:
        # guarda os parâmetros da requisição para retomar após o round-trip SSO
        rid = secrets.token_urlsafe(16)
        STORE.save_auth_code(f"authreq:{rid}", {
            "client_id": client_id, "redirect_uri": redirect_uri, "resource": resource,
            "scope": " ".join(granted), "code_challenge": code_challenge, "state": state,
        }, ttl=CODE_TTL)
    fields = {
        "client_id": client_id, "redirect_uri": redirect_uri, "scope": " ".join(granted),
        "state": state, "code_challenge": code_challenge, "resource": resource, "_rid": rid,
    }
    return HTMLResponse(_render_login_consent(fields, granted, client))


def _issue_code_redirect(*, client_id, redirect_uri, resource, scope, code_challenge,
                         subject, tenant_id, state, role="user") -> RedirectResponse:
    """Cria o authorization code (ligado ao usuário autenticado) e redireciona ao cliente."""
    code = secrets.token_urlsafe(32)
    STORE.save_auth_code(code, {
        "client_id": client_id, "redirect_uri": redirect_uri, "resource": resource,
        "scope": scope, "code_challenge": code_challenge,
        "subject": subject, "tenant_id": tenant_id, "role": role,
    }, ttl=CODE_TTL)
    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)


@app.post("/oauth/authorize")
async def authorize_post(
    client_id: str = Form(...), redirect_uri: str = Form(...), code_challenge: str = Form(...),
    resource: str = Form(...), scope: str = Form(""), state: str = Form(""),
    username: str = Form(""), password: str = Form(""), decision: str = Form("deny"),
):
    client = STORE.get_client(client_id)
    if not client or redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "invalid_client")

    if decision != "approve":
        params = {"error": "access_denied"}
        if state:
            params["state"] = state
        return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

    # LOGIN real: valida credenciais antes de emitir o code.
    user = USER_STORE.verify(username, password)
    if user is None:
        granted = scope.split()
        fields = {
            "client_id": client_id, "redirect_uri": redirect_uri, "scope": scope,
            "state": state, "code_challenge": code_challenge, "resource": resource, "_rid": "",
        }
        page = _render_login_consent(fields, granted, client, error="Usuário ou senha inválidos.")
        return HTMLResponse(page, status_code=401)

    return _issue_code_redirect(
        client_id=client_id, redirect_uri=redirect_uri, resource=resource, scope=scope,
        code_challenge=code_challenge, subject=user.subject, tenant_id=user.tenant_id,
        state=state, role=user.role,
    )


# ── Federação SSO (OIDC upstream) — opcional, config-gated ─────────────────── #

@app.get("/oauth/sso/start")
async def sso_start(rid: str):
    if not UPSTREAM.enabled:
        raise HTTPException(404, "SSO não configurado")
    req = STORE.take_auth_code(f"authreq:{rid}")  # single-use; re-salva p/ o callback consumir
    if not req:
        raise HTTPException(400, "requisição de autorização expirada")
    # nonce (anti-replay) + PKCE (anti-interceptação de code) para a perna auth-mcp→IdP
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = _gen_pkce()
    req["oidc_nonce"] = nonce
    req["oidc_verifier"] = verifier
    STORE.save_auth_code(f"authreq:{rid}", req, ttl=CODE_TTL)
    url = UPSTREAM.build_authorization_url(state=rid, nonce=nonce, code_challenge=challenge)
    return RedirectResponse(url, status_code=302)


@app.get("/oauth/sso/callback")
async def sso_callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if not UPSTREAM.enabled:
        raise HTTPException(404, "SSO não configurado")
    req = STORE.take_auth_code(f"authreq:{state}")  # valida state (anti-CSRF) e consome
    if not req:
        raise HTTPException(400, "requisição de autorização expirada ou state inválido")

    # o IdP pode devolver erro em vez de code
    if error or not code:
        params = {"error": error or "access_denied"}
        if req.get("state"):
            params["state"] = req["state"]
        return RedirectResponse(f"{req['redirect_uri']}?{urlencode(params)}", status_code=302)

    try:
        identity = await UPSTREAM.exchange_and_validate(
            code, code_verifier=req["oidc_verifier"], expected_nonce=req["oidc_nonce"])
    except OIDCError as e:
        logging.warning("Falha OIDC upstream: %s", e)
        params = {"error": "access_denied", "error_description": "falha na autenticação SSO"}
        if req.get("state"):
            params["state"] = req["state"]
        return RedirectResponse(f"{req['redirect_uri']}?{urlencode(params)}", status_code=302)

    return _issue_code_redirect(
        client_id=req["client_id"], redirect_uri=req["redirect_uri"], resource=req["resource"],
        scope=req["scope"], code_challenge=req["code_challenge"],
        subject=f"oidc:{identity['sub']}", tenant_id="default",
        state=req.get("state", ""), role=identity.get("role", "user"),
    )


# ============================================================================
# Token endpoint
# ============================================================================

@app.post("/oauth/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    # authorization_code
    code: str = Form(None), redirect_uri: str = Form(None), code_verifier: str = Form(None),
    # refresh
    refresh_token: str = Form(None),
    # comum
    scope: str = Form(""), resource: str = Form(""),
    client_id: str = Form(None), client_secret: str = Form(None),
):
    if grant_type == "authorization_code":
        return await _grant_authorization_code(code, redirect_uri, code_verifier, client_id, client_secret)
    if grant_type == "refresh_token":
        return await _grant_refresh(refresh_token, scope)
    if grant_type == "client_credentials":
        return await _grant_client_credentials(request, scope, resource, client_id, client_secret)
    raise HTTPException(400, {"error": "unsupported_grant_type"})


def _issue_refresh(subject: str, resource: str, scopes: list[str], tenant_id: str, client_id: str) -> str | None:
    if "offline_access" not in scopes:
        return None
    rt = secrets.token_urlsafe(40)
    STORE.save_refresh(rt, {
        "subject": subject, "resource": resource, "scope": " ".join(scopes),
        "tenant_id": tenant_id, "client_id": client_id,
    }, ttl=REFRESH_TTL)
    return rt


async def _grant_authorization_code(code, redirect_uri, code_verifier, client_id, client_secret):
    if not code or not code_verifier:
        raise HTTPException(400, {"error": "invalid_request", "error_description": "code e code_verifier obrigatórios"})
    data = STORE.take_auth_code(code)
    if not data:
        return JSONResponse({"error": "invalid_grant", "error_description": "code inválido/expirado/usado"}, 400)
    if data["client_id"] != client_id or data["redirect_uri"] != redirect_uri:
        return JSONResponse({"error": "invalid_grant", "error_description": "client/redirect divergente"}, 400)

    client = STORE.get_client(client_id)
    if client and not client.is_public:
        if not client_secret or not client.client_secret_hash or \
           not bcrypt.checkpw(client_secret.encode(), client.client_secret_hash):
            return JSONResponse({"error": "invalid_client"}, 401)

    # PKCE S256
    if _b64url_sha256(code_verifier) != data["code_challenge"]:
        return JSONResponse({"error": "invalid_grant", "error_description": "PKCE falhou"}, 400)

    scopes = data["scope"].split()
    access = _mint_access(data["subject"], data["resource"], scopes, data["tenant_id"],
                          client_id, role=data.get("role", "user"))
    rt = _issue_refresh(data["subject"], data["resource"], scopes, data["tenant_id"], client_id)
    body = {"access_token": access, "token_type": "Bearer", "expires_in": DEFAULT_TTL, "scope": " ".join(scopes)}
    if rt:
        body["refresh_token"] = rt
    return body


async def _grant_refresh(refresh_token, scope):
    if not refresh_token:
        raise HTTPException(400, {"error": "invalid_request"})
    data = STORE.take_refresh(refresh_token)  # single-use → rotação
    if not data:
        return JSONResponse({"error": "invalid_grant", "error_description": "refresh inválido/expirado/usado"}, 400)
    scopes = data["scope"].split()
    if scope:  # downscoping permitido, upscoping não
        requested = set(scope.split())
        scopes = [s for s in scopes if s in requested] or scopes
    access = _mint_access(data["subject"], data["resource"], scopes, data["tenant_id"], data["client_id"])
    rt = _issue_refresh(data["subject"], data["resource"], scopes, data["tenant_id"], data["client_id"])
    body = {"access_token": access, "token_type": "Bearer", "expires_in": DEFAULT_TTL, "scope": " ".join(scopes)}
    if rt:
        body["refresh_token"] = rt
    return body


async def _grant_client_credentials(request, scope, resource, client_id, client_secret):
    if not client_id:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                client_id, client_secret = base64.b64decode(auth[6:]).decode().split(":", 1)
            except Exception:
                raise HTTPException(401, {"error": "invalid_client"})
    client = STORE.get_client(client_id or "")
    if not client or not client.client_secret_hash or not client_secret or \
       not bcrypt.checkpw(client_secret.encode(), client.client_secret_hash):
        return JSONResponse({"error": "invalid_client"}, 401, headers={"WWW-Authenticate": "Basic"})
    if not resource:
        raise HTTPException(400, {"error": "invalid_target", "error_description": "resource (RFC 8707) obrigatório"})
    granted = _authorized_scopes(scope, client.scopes)
    access = _mint_access(client.subject, resource, granted, "default", client_id)
    return {"access_token": access, "token_type": "Bearer", "expires_in": DEFAULT_TTL, "scope": " ".join(granted)}


@app.post("/oauth/introspect")
async def introspect(token: str = Form(...)):
    try:
        claims = jwt.decode(token, PUBLIC_PEM, algorithms=["RS256"], options={"verify_aud": False})
        return {"active": True, **{k: claims.get(k) for k in ("sub", "aud", "scope", "exp", "iss", "client_id")}}
    except jwt.PyJWTError:
        return {"active": False}


@app.get("/v1/health")
@app.get("/health")
async def health():
    return {"status": "ok", "server": "auth-mcp-as", "issuer": ISSUER}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7103")))


if __name__ == "__main__":
    main()
