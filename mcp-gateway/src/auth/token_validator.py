"""Validação de Bearer tokens do MCP Gateway (autenticação REAL).

Implementa o padrão de autenticação descrito em MCP_SERVICE_STANDARD.md §6/§7:

- **Bootstrap (static tokens):** Bearer opaco por usuário, validado com bcrypt.
  Os registros vêm da env ``GATEWAY_STATIC_TOKENS_JSON`` (equivalente à tabela
  ``agent_tokens`` do Postgres em produção), respeitando ``expires_at``/``revoked``.
- **Produção (JWT OAuth):** access token JWT (RS256) validado via PyJWT — assinatura
  por JWKS (``PyJWKClient``) ou por chave pública PEM injetável, com verificação de
  ``aud`` (== ``GATEWAY_RESOURCE``), ``iss`` (== ``GATEWAY_AS_ISSUER``) e ``exp``.

IMPORTANTE — DUPLICAÇÃO INTENCIONAL:
    A lógica de StaticTokenStore + JwtValidator espelha ``shared/mcp_auth.py``. Ela é
    reimplementada aqui de forma SELF-CONTAINED porque o ``Dockerfile`` do gateway copia
    somente ``src/`` (build context = ./mcp-gateway); ``shared/`` NÃO existe na imagem.
    Por isso NÃO importamos ``shared.mcp_auth`` — a duplicação é deliberada.

A interface pública (``UserSession``, ``async def validate_token``,
``async def authenticate_request``) é preservada EXATAMENTE, pois é consumida por
``src/proxy/router.py`` e ``src/auth/rbac.py``.

--------------------------------------------------------------------------------
Como gerar um static token e seu hash bcrypt (o token opaco é o segredo; guarde só o hash):

    python -c "import bcrypt, secrets; \
raw = secrets.token_urlsafe(32); \
print('TOKEN =', raw); \
print('HASH  =', bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode())"

O ``TOKEN`` vai para o cliente (``Authorization: Bearer <TOKEN>``); o ``HASH`` vai para
a env ``GATEWAY_STATIC_TOKENS_JSON``.

Formato de GATEWAY_STATIC_TOKENS_JSON (aceita duas formas):

    # 1) Lista de registros (forma preferida):
    [
      {
        "token_hash": "<hash bcrypt>",
        "user_id": "admin",
        "role": "admin",
        "scopes": ["*"],
        "tenant_id": "acme",
        "expires_at": null,      # epoch (int) ou null
        "revoked": false
      }
    ]

    # 2) Mapa hash -> registro (compatibilidade):
    {
      "<hash bcrypt>": {
        "user_id": "dev1",
        "role": "developer",
        "scopes": ["qa-engineer-mcp", "backend-mcp"],
        "tenant_id": "acme"
      }
    }

Envs de JWT (produção):
    GATEWAY_AS_ISSUER      — issuer esperado (claim ``iss``).
    GATEWAY_RESOURCE       — audience esperado (claim ``aud``), a URL deste resource.
    GATEWAY_AS_JWKS_URL    — URL do JWKS do Authorization Server (assinatura por JWKS).
    GATEWAY_AS_PUBLIC_KEY_PEM — alternativa ao JWKS: chave pública RSA em PEM (útil em
                                testes/ambientes sem HTTP). Se ambos estiverem setados,
                                o JWKS tem prioridade.
    GATEWAY_JWT_LEEWAY     — folga (segundos) para exp/nbf; default 30.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import bcrypt


# ============================================================================
# Interface pública — NÃO ALTERAR (consumida por router.py e rbac.py)
# ============================================================================

@dataclass
class UserSession:
    user_id: str
    role: str
    scopes: list[str]
    tenant_id: str
    actor_type: str = "human"


# ============================================================================
# Static tokens (bootstrap) — Bearer opaco por usuário com hash bcrypt
# ============================================================================

@dataclass
class _StaticTokenRecord:
    """Registro de um token estático (espelha a linha da tabela agent_tokens)."""
    token_hash: bytes            # hash bcrypt do token opaco
    user_id: str
    role: str
    scopes: list[str]
    tenant_id: str
    actor_type: str = "human"
    expires_at: int | None = None
    revoked: bool = False


class _StaticTokenStore:
    """Valida tokens estáticos opacos com bcrypt, respeitando expiração/revogação."""

    def __init__(self, records: list[_StaticTokenRecord] | None = None):
        self.records = records or []

    def validate(self, raw_token: str) -> UserSession | None:
        now = int(time.time())
        raw = raw_token.encode()
        for rec in self.records:
            if rec.revoked:
                continue
            if rec.expires_at is not None and now >= rec.expires_at:
                continue
            try:
                if bcrypt.checkpw(raw, rec.token_hash):
                    if not (rec.user_id and rec.tenant_id):
                        return None
                    return UserSession(
                        user_id=rec.user_id,
                        role=rec.role,
                        scopes=list(rec.scopes),
                        tenant_id=rec.tenant_id,
                        actor_type=rec.actor_type,
                    )
            except (ValueError, TypeError):
                # hash malformado no registro — ignora e continua
                continue
        return None


def _coerce_hash(value: Any) -> bytes:
    """Normaliza o token_hash para bytes (JSON traz str)."""
    if isinstance(value, bytes):
        return value
    return str(value).encode()


def _parse_static_records(payload: str | None) -> list[_StaticTokenRecord]:
    """Faz o parse de GATEWAY_STATIC_TOKENS_JSON nas duas formas suportadas."""
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return []

    records: list[_StaticTokenRecord] = []

    if isinstance(data, list):
        # Forma 1: lista de registros
        for item in data:
            if not isinstance(item, dict):
                continue
            token_hash = item.get("token_hash")
            if not token_hash:
                continue
            records.append(
                _StaticTokenRecord(
                    token_hash=_coerce_hash(token_hash),
                    user_id=item.get("user_id", ""),
                    role=item.get("role", "developer"),
                    scopes=list(item.get("scopes", [])),
                    tenant_id=item.get("tenant_id", ""),
                    actor_type=item.get("actor_type", "human"),
                    expires_at=item.get("expires_at"),
                    revoked=bool(item.get("revoked", False)),
                )
            )
    elif isinstance(data, dict):
        # Forma 2: mapa hash -> registro
        for token_hash, item in data.items():
            if not isinstance(item, dict):
                continue
            records.append(
                _StaticTokenRecord(
                    token_hash=_coerce_hash(token_hash),
                    user_id=item.get("user_id", ""),
                    role=item.get("role", "developer"),
                    scopes=list(item.get("scopes", [])),
                    tenant_id=item.get("tenant_id", ""),
                    actor_type=item.get("actor_type", "human"),
                    expires_at=item.get("expires_at"),
                    revoked=bool(item.get("revoked", False)),
                )
            )
    return records


# ============================================================================
# JWT (produção) — validação RS256 via JWKS ou chave pública PEM
# ============================================================================

class _JwtValidator:
    """Valida access tokens JWT (RS256) emitidos pelo Authorization Server.

    Aceita chave via JWKS remoto (produção) ou PEM injetável (teste/bootstrap).
    Importa PyJWT preguiçosamente para não exigir a dep se JWT não for usado.
    """

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        public_key_pem: str | None = None,
        leeway: int = 30,
    ):
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self.public_key_pem = public_key_pem
        self.leeway = leeway
        self._jwks_client = None  # lazy

    def _signing_key(self, token: str):
        # JWKS tem prioridade sobre PEM
        if self.jwks_url:
            from jwt import PyJWKClient
            if self._jwks_client is None:
                self._jwks_client = PyJWKClient(self.jwks_url)
            return self._jwks_client.get_signing_key_from_jwt(token).key
        if self.public_key_pem:
            return self.public_key_pem
        return None

    def validate(self, token: str) -> UserSession | None:
        import jwt

        try:
            key = self._signing_key(token)
            if key is None:
                return None
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError:
            # assinatura/aud/iss/exp inválidos → sem sessão
            return None
        except Exception:
            # falha ao obter chave (JWKS indisponível etc.) → sem sessão
            return None

        scope_raw = claims.get("scope", "")
        if isinstance(scope_raw, str):
            scopes = scope_raw.split()
        else:
            scopes = list(scope_raw)

        user_id = claims.get("sub", "")
        tenant_id = claims.get("tenant_id", "")
        if not (user_id and tenant_id):
            return None
        return UserSession(
            user_id=user_id,
            role=claims.get("role", "user"),
            scopes=scopes,
            tenant_id=tenant_id,
            actor_type=claims.get("actor_type", "human"),
        )


def _looks_like_jwt(token: str) -> bool:
    """Um JWT tem exatamente 3 segmentos separados por ponto."""
    return token.count(".") == 2 and all(part for part in token.split("."))


def _build_jwt_validator() -> _JwtValidator | None:
    """Monta o validador de JWT a partir das envs, se configuradas."""
    issuer = os.environ.get("GATEWAY_AS_ISSUER")
    audience = os.environ.get("GATEWAY_RESOURCE")
    jwks_url = os.environ.get("GATEWAY_AS_JWKS_URL")
    public_key_pem = os.environ.get("GATEWAY_AS_PUBLIC_KEY_PEM")

    # Precisa de issuer + audience + (JWKS URL OU PEM).
    if not (issuer and audience and (jwks_url or public_key_pem)):
        return None

    try:
        leeway = int(os.environ.get("GATEWAY_JWT_LEEWAY", "30"))
    except (TypeError, ValueError):
        leeway = 30

    return _JwtValidator(
        issuer=issuer,
        audience=audience,
        jwks_url=jwks_url,
        public_key_pem=public_key_pem,
        leeway=leeway,
    )


# ============================================================================
# API pública (assinaturas preservadas)
# ============================================================================

async def validate_token(raw_token: str) -> UserSession | None:
    """Valida um Bearer token opaco/JWT e devolve a UserSession, ou None.

    Ordem de tentativa:
      1. JWT — se o token parecer JWT (3 segmentos) e as envs de JWT estiverem setadas.
      2. Static token (bcrypt) — a partir de GATEWAY_STATIC_TOKENS_JSON.
    Sem match → None. Os tokens de teste hardcoded foram REMOVIDOS.

    As envs são lidas a cada chamada de propósito, para refletir mudanças de
    configuração (e permitir monkeypatch em testes) sem reiniciar o processo.
    """
    if not raw_token:
        return None

    # 1) JWT (produção)
    if _looks_like_jwt(raw_token):
        validator = _build_jwt_validator()
        if validator is not None:
            session = validator.validate(raw_token)
            if session is not None:
                return session

    # 2) Static token (bootstrap)
    store = _StaticTokenStore(_parse_static_records(os.environ.get("GATEWAY_STATIC_TOKENS_JSON")))
    return store.validate(raw_token)


async def authenticate_request(auth_header: str | None) -> UserSession | None:
    """Extrai e valida o Bearer token do header Authorization."""
    if not auth_header:
        return None

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:].strip()
    return await validate_token(token)
