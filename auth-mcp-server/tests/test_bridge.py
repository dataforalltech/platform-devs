"""Testes unitários da PONTE Twin Token (D4.7) — Fase 2 do MCP_OAUTH_FRONTDOOR_DESIGN.md.

Cobre: shared.twin_session_client.mint_twin_session (construção do request + erro),
e os seams do AS em authorization_server (_seconds_until, _platform_user_id,
_resolve_platform_user_jwt, _mint_access em modo ponte / fallback / S2S).

e2e (discovery→DCR→PKCE→token→refresh contra admin real) fica pendente (Fase 0 não semeada).
"""
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import authorization_server as A
from shared.twin_session_client import TwinSessionError, mint_twin_session


def _rsa_pem() -> tuple[str, str]:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = k.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


def _iso_in(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ── shared/twin_session_client.mint_twin_session ────────────────────────────── #

def test_mint_twin_session_builds_request():
    seen = {}

    def fake(url, data, headers, timeout):
        seen["url"] = url
        seen["body"] = json.loads(data.decode())
        seen["headers"] = headers
        return 201, json.dumps({"token": "TWIN", "expiresAt": _iso_in(900), "jti": "j", "scopes": [], "twinId": 1})

    resp = mint_twin_session(
        admin_base_url="http://admin:8000/", user_jwt="UJWT", tenant_id="T1",
        internal_token="ITOK", agent_id="claude-code-desktop", audiences=["mcp:gateway"],
        _transport=fake,
    )
    assert resp["token"] == "TWIN"
    assert seen["url"] == "http://admin:8000/api/v1/twin/sessions"
    assert seen["headers"]["Authorization"] == "Bearer UJWT"
    assert seen["headers"]["X-Tenant-Id"] == "T1"
    assert seen["headers"]["X-Internal-Token"] == "ITOK"
    assert seen["body"] == {"agentId": "claude-code-desktop", "audiences": ["mcp:gateway"]}


def test_mint_twin_session_raises_on_http_error():
    def fake(url, data, headers, timeout):
        return 401, '{"code":"missing_internal_token"}'

    with pytest.raises(TwinSessionError) as ei:
        mint_twin_session(admin_base_url="http://a", user_jwt="u", tenant_id="t",
                          internal_token="i", agent_id="a", _transport=fake)
    assert ei.value.status == 401


# ── _seconds_until ──────────────────────────────────────────────────────────── #

def test_seconds_until_future():
    assert 850 < A._seconds_until(_iso_in(900)) <= 900


def test_seconds_until_fallbacks():
    assert A._seconds_until(None) == A.DEFAULT_TTL
    assert A._seconds_until("not-a-date") == A.DEFAULT_TTL


# ── _platform_user_id (R1) ──────────────────────────────────────────────────── #

def test_platform_user_id_numeric():
    assert A._platform_user_id("user:42") == "42"
    assert A._platform_user_id("7") == "7"


def test_platform_user_id_via_map(monkeypatch):
    monkeypatch.setenv("AS_SUBJECT_USERID_MAP", json.dumps({"oidc:abc": 99}))
    assert A._platform_user_id("oidc:abc") == "99"


def test_platform_user_id_unmapped_raises(monkeypatch):
    monkeypatch.delenv("AS_SUBJECT_USERID_MAP", raising=False)
    with pytest.raises(TwinSessionError):
        A._platform_user_id("oidc:nobody")


# ── _resolve_platform_user_jwt ──────────────────────────────────────────────── #

def test_resolve_platform_user_jwt(monkeypatch):
    priv, pub = _rsa_pem()
    monkeypatch.setattr(A, "PLATFORM_JWT_KEY_PEM", priv)
    monkeypatch.setattr(A, "PLATFORM_JWT_KEY_FILE", None)
    monkeypatch.setattr(A, "PLATFORM_JWT_AUDIENCE", "platform-services")
    monkeypatch.setattr(A, "PLATFORM_JWT_ISSUER", "platform-auth")
    tok = A._resolve_platform_user_jwt("user:5", "T1")
    claims = jwt.decode(tok, pub, algorithms=["RS256"], audience="platform-services")
    assert claims["sub"] == "5"
    assert claims["iss"] == "platform-auth"
    assert claims["tenant_id"] == "T1"
    assert jwt.get_unverified_header(tok)["kid"] == A.PLATFORM_JWT_KID


def test_resolve_platform_user_jwt_missing_key_raises(monkeypatch):
    monkeypatch.setattr(A, "PLATFORM_JWT_KEY_PEM", None)
    monkeypatch.setattr(A, "PLATFORM_JWT_KEY_FILE", None)
    with pytest.raises(TwinSessionError):
        A._resolve_platform_user_jwt("user:5", "T1")


# ── _mint_access ────────────────────────────────────────────────────────────── #

def test_mint_access_bridge_returns_twin_and_ttl(monkeypatch):
    monkeypatch.setattr(A, "BRIDGE_TWIN", True)
    monkeypatch.setattr(A, "ADMIN_BASE_URL", "http://admin:8000")
    monkeypatch.setattr(A, "ADMIN_INTERNAL_TOKEN", "ITOK")
    monkeypatch.setattr(A, "_resolve_platform_user_jwt", lambda s, t: "UJWT")
    seen = {}

    def fake_mint(**kw):
        seen.update(kw)
        return {"token": "TWIN-JWT", "expiresAt": _iso_in(900)}

    monkeypatch.setattr(A, "mint_twin_session", fake_mint)
    tok, ttl = A._mint_access("user:5", "https://gw", ["x"], "T1", "dcr-1")
    assert tok == "TWIN-JWT"
    assert 850 < ttl <= 900
    assert seen["audiences"] == A.TWIN_AUDIENCES
    assert seen["agent_id"] == A.TWIN_AGENT_ID
    assert seen["tenant_id"] == "T1"
    assert seen["user_jwt"] == "UJWT"


def test_mint_access_bridge_off_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(A, "BRIDGE_TWIN", False)
    tok, ttl = A._mint_access("user:5", "https://gw", ["x"], "T1", "dcr-1")
    assert ttl == A.DEFAULT_TTL
    claims = jwt.decode(tok, A.PUBLIC_PEM, algorithms=["RS256"], options={"verify_aud": False})
    assert claims["sub"] == "user:5"
    assert claims["tenant_id"] == "T1"


def test_mint_access_service_subject_never_bridges(monkeypatch):
    monkeypatch.setattr(A, "BRIDGE_TWIN", True)
    monkeypatch.setattr(A, "ADMIN_BASE_URL", "http://admin:8000")
    monkeypatch.setattr(A, "ADMIN_INTERNAL_TOKEN", "ITOK")

    def boom(**kw):
        raise AssertionError("client_credentials/svc subject não deve passar pela PONTE")

    monkeypatch.setattr(A, "mint_twin_session", boom)
    tok, ttl = A._mint_access("svc:security-dev", "https://res", ["security:*"], "default", "security-dev", bridge=False)
    assert ttl == A.DEFAULT_TTL
