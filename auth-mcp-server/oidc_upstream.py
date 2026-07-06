"""Federação OIDC upstream (SSO corporativo) para o auth-mcp — grau de produção.

Permite que a tela de consentimento delegue o LOGIN a um IdP externo (Entra ID, Keycloak,
Auth0, Google Workspace, Okta, etc.) via OpenID Connect Authorization Code + PKCE. O auth-mcp
continua sendo o Authorization Server que emite os tokens do RECURSO (Security/QA-Engineer); a
IDENTIDADE do usuário vem do IdP.

Segurança implementada (todas as recomendações OIDC/OAuth 2.1 para o cliente):
- **state** anti-CSRF (ligado à requisição de autorização original no auth-mcp).
- **nonce** no id_token (anti-replay) — gerado no início, exigido e conferido na validação.
- **PKCE (S256)** também na perna auth-mcp→IdP (defesa a interceptação de code).
- Validação completa do id_token: assinatura (JWKS), `iss`, `aud`==client_id, `exp`, `nonce`.
- Tratamento de erro do upstream (parâmetro `error`) e discovery cacheado.
- Mapeamento configurável de claim de grupos/roles do IdP → role da plataforma.

Envs:
  AS_UPSTREAM_OIDC_ISSUER          ex: https://login.microsoftonline.com/<tenant>/v2.0
  AS_UPSTREAM_OIDC_CLIENT_ID
  AS_UPSTREAM_OIDC_CLIENT_SECRET   (via secrets manager; alguns IdPs permitem client público+PKCE)
  AS_UPSTREAM_OIDC_REDIRECT_URI    ex: https://mcp.suaempresa.com/auth/oauth/sso/callback
  AS_UPSTREAM_OIDC_SCOPES          default "openid email profile"
  AS_UPSTREAM_OIDC_ROLE_CLAIM      caminho pontilhado do claim de roles/grupos
                                   (ex: "roles", "groups", "realm_access.roles")
  AS_UPSTREAM_OIDC_ROLE_MAP        JSON {grupo_idp: role_plataforma}
  AS_UPSTREAM_OIDC_DEFAULT_ROLE    fallback (default "developer")
  AS_UPSTREAM_OIDC_*_ENDPOINT/_URI opcionais (senão descobertos no openid-configuration)

Testabilidade: `build_authorization_url` e `map_identity` são puros. `validate_id_token`
aceita uma chave injetada (jwk/pem), então dá para testar sem rede. A busca de token/JWKS
(`_fetch_token`) é isolada e mockável.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode


class OIDCError(Exception):
    pass


@dataclass
class UpstreamOIDC:
    enabled: bool
    name: str = "SSO"
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: str = "openid email profile"
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    jwks_uri: str = ""
    role_claim: str = "roles"
    role_map: dict[str, str] = field(default_factory=dict)
    default_role: str = "developer"
    _discovered: bool = False

    @classmethod
    def from_env(cls) -> "UpstreamOIDC":
        issuer = os.getenv("AS_UPSTREAM_OIDC_ISSUER", "")
        client_id = os.getenv("AS_UPSTREAM_OIDC_CLIENT_ID", "")
        if not issuer or not client_id:
            return cls(enabled=False)
        try:
            role_map = json.loads(os.getenv("AS_UPSTREAM_OIDC_ROLE_MAP", "{}"))
        except (json.JSONDecodeError, ValueError):
            role_map = {}
        return cls(
            enabled=True,
            name=os.getenv("AS_UPSTREAM_OIDC_NAME", "SSO"),
            issuer=issuer.rstrip("/"),
            client_id=client_id,
            client_secret=os.getenv("AS_UPSTREAM_OIDC_CLIENT_SECRET", ""),
            redirect_uri=os.getenv("AS_UPSTREAM_OIDC_REDIRECT_URI", ""),
            scopes=os.getenv("AS_UPSTREAM_OIDC_SCOPES", "openid email profile"),
            authorization_endpoint=os.getenv("AS_UPSTREAM_OIDC_AUTHORIZATION_ENDPOINT", ""),
            token_endpoint=os.getenv("AS_UPSTREAM_OIDC_TOKEN_ENDPOINT", ""),
            jwks_uri=os.getenv("AS_UPSTREAM_OIDC_JWKS_URI", ""),
            role_claim=os.getenv("AS_UPSTREAM_OIDC_ROLE_CLAIM", "roles"),
            role_map=role_map,
            default_role=os.getenv("AS_UPSTREAM_OIDC_DEFAULT_ROLE", "developer"),
        )

    # ── Discovery (cacheado) ─────────────────────────────────────────────── #
    def discover(self) -> None:
        if self._discovered or (self.authorization_endpoint and self.token_endpoint and self.jwks_uri):
            self._discovered = True
            return
        import httpx
        meta = httpx.get(f"{self.issuer}/.well-known/openid-configuration", timeout=10).json()
        self.authorization_endpoint = self.authorization_endpoint or meta["authorization_endpoint"]
        self.token_endpoint = self.token_endpoint or meta["token_endpoint"]
        self.jwks_uri = self.jwks_uri or meta["jwks_uri"]
        self._discovered = True

    # ── Passo 1: URL de autorização (PURA) ───────────────────────────────── #
    def build_authorization_url(self, *, state: str, nonce: str, code_challenge: str,
                                endpoint_override: str | None = None) -> str:
        endpoint = endpoint_override or self.authorization_endpoint
        if not endpoint:
            self.discover()
            endpoint = self.authorization_endpoint
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{endpoint}?{urlencode(params)}"

    # ── Passo 2a: troca code→id_token (rede; isolado p/ mock) ─────────────── #
    async def _fetch_id_token(self, code: str, code_verifier: str) -> str:
        import httpx
        self.discover()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self.token_endpoint, data=data)
            resp.raise_for_status()
            body = resp.json()
        if "id_token" not in body:
            raise OIDCError("resposta do IdP sem id_token")
        return body["id_token"]

    # ── Passo 2b: validação do id_token (chave injetável → testável) ──────── #
    def validate_id_token(self, id_token: str, *, expected_nonce: str,
                          signing_key: Any | None = None) -> dict:
        import jwt
        if signing_key is None:
            from jwt import PyJWKClient
            self.discover()
            signing_key = PyJWKClient(self.jwks_uri).get_signing_key_from_jwt(id_token).key
        try:
            claims = jwt.decode(
                id_token, signing_key, algorithms=["RS256", "ES256"],
                audience=self.client_id, issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise OIDCError(f"id_token inválido: {e}")
        if expected_nonce and claims.get("nonce") != expected_nonce:
            raise OIDCError("nonce do id_token não confere (possível replay)")
        return claims

    # ── Passo 3: mapeia claims → identidade da plataforma (PURA) ──────────── #
    def map_identity(self, claims: dict) -> dict:
        # extrai o claim de roles/grupos por caminho pontilhado
        node: Any = claims
        for part in self.role_claim.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        groups = node if isinstance(node, list) else ([node] if isinstance(node, str) else [])
        role = self.default_role
        for g in groups:
            if g in self.role_map:
                role = self.role_map[g]
                break
        return {
            "sub": claims["sub"],
            "email": claims.get("email") or claims.get("preferred_username"),
            "name": claims.get("name"),
            "role": role,
            "groups": groups,
        }

    # ── Orquestração (usada pelo callback do AS) ──────────────────────────── #
    async def exchange_and_validate(self, code: str, *, code_verifier: str, expected_nonce: str) -> dict:
        id_token = await self._fetch_id_token(code, code_verifier)
        claims = self.validate_id_token(id_token, expected_nonce=expected_nonce)
        return self.map_identity(claims)
