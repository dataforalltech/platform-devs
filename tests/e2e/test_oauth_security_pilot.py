"""E2E do piloto: auth-mcp (AS) emite token → Security (Streamable HTTP) valida e autoriza.

Roda in-process com TestClient. Ordem de import evita os shadows de mcp/ e src/ da raiz:
importa o SDK real 'mcp' ANTES de qualquer sys.path que aponte para a raiz do repo.
"""
import asyncio
import importlib.util
import json
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEC = os.path.join(ROOT, "security-mcp-server")
AS_FILE = os.path.join(ROOT, "auth-mcp-server", "authorization_server.py")

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name)

# 1) registra 'shared' por caminho e carrega shared.mcp_auth (sem pôr ROOT no path → mcp real intacto)
shared_pkg = types.ModuleType("shared"); shared_pkg.__path__ = [os.path.join(ROOT, "shared")]
sys.modules["shared"] = shared_pkg
spec = importlib.util.spec_from_file_location("shared.mcp_auth", os.path.join(ROOT, "shared", "mcp_auth.py"))
mcp_auth = importlib.util.module_from_spec(spec); sys.modules["shared.mcp_auth"] = mcp_auth
spec.loader.exec_module(mcp_auth)

# 2) importa o servidor do Security (usa o SDK 'mcp' real — ROOT ainda não está no path)
sys.path.insert(0, SEC)
from src.server import mcp_server as sec  # noqa: E402

# 3) carrega o Authorization Server por caminho (ele insere ROOT no path, mas 'mcp' já está cacheado)
#    auth-mcp-server precisa estar no path para o AS importar seu módulo irmão oidc_upstream
sys.path.insert(0, os.path.join(ROOT, "auth-mcp-server"))
spec_as = importlib.util.spec_from_file_location("authorization_server", AS_FILE)
AS = importlib.util.module_from_spec(spec_as); spec_as.loader.exec_module(AS)

from starlette.testclient import TestClient  # noqa: E402

RESOURCE = sec.RESOURCE  # audience que o Security exige

print("\n[A] Authorization Server emite token (client_credentials)")
as_client = TestClient(AS.app)
r = as_client.post("/oauth/token", data={
    "grant_type": "client_credentials", "client_id": "security-dev",
    "client_secret": os.getenv("AS_DEMO_SECRET", "dev-secret-change-me"),
    "resource": RESOURCE, "scope": "security:scan",
})
check("token endpoint 200", r.status_code == 200)
tok = r.json()
check("access_token presente", "access_token" in tok)
check("scope concedido = security:scan", tok.get("scope") == "security:scan")
scan_token = tok.get("access_token", "")

# token só-leitura (client tem security:* então pode pedir security:read)
r_ro = as_client.post("/oauth/token", data={
    "grant_type": "client_credentials", "client_id": "security-dev",
    "client_secret": "dev-secret-change-me", "resource": RESOURCE, "scope": "security:read",
})
read_token = r_ro.json().get("access_token", "")

# token para OUTRO recurso (audience errado)
r_wrong = as_client.post("/oauth/token", data={
    "grant_type": "client_credentials", "client_id": "security-dev",
    "client_secret": "dev-secret-change-me", "resource": "http://evil/other", "scope": "security:scan",
})
wrong_aud_token = r_wrong.json().get("access_token", "")

print("\n[B] JWKS / discovery")
jwks = as_client.get("/.well-known/jwks.json").json()
check("jwks tem 1 chave", len(jwks.get("keys", [])) == 1)
meta = as_client.get("/.well-known/oauth-authorization-server").json()
check("metadata tem token_endpoint", "token_endpoint" in meta)

print("\n[C] Validador do Security (via chave pública do AS)")
validator = mcp_auth.JwtValidator(issuer=AS.ISSUER, audience=RESOURCE, jwk=AS.PUBLIC_JWK)
p = validator.validate(scan_token)
check("valida token bom → subject", p.subject == "svc:security-dev")
check("principal tem scope security:scan", p.has_scope("security:scan"))
try:
    validator.validate(wrong_aud_token); check("rejeita audience errado", False)
except mcp_auth.AuthError as e:
    check("rejeita audience errado (invalid_token)", e.error == "invalid_token")

print("\n[D] Security Streamable HTTP + middleware de auth")
app = sec.build_app(validators=[validator.validate])

hdr_mcp = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
init_body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "e2e", "version": "1"}}}
call_scan = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "review_secure_code", "arguments": {"code": "x=1", "language": "python"}}}

# context manager dispara o lifespan (inicializa o task group do session manager)
with TestClient(app) as sc:
    # health público sem token
    check("health público 200", sc.get("/v1/health").status_code == 200)
    # PRM público
    prm = sc.get("/.well-known/oauth-protected-resource")
    check("PRM 200 + aponta AS", prm.status_code == 200 and AS.ISSUER in prm.json().get("authorization_servers", []))

    # sem token → 401 + WWW-Authenticate
    r401 = sc.post("/mcp", headers=hdr_mcp, json=init_body)
    check("sem token → 401", r401.status_code == 401)
    check("401 traz resource_metadata", "resource_metadata" in r401.headers.get("WWW-Authenticate", ""))

    # initialize com token válido → não-401
    r_init = sc.post("/mcp", headers={**hdr_mcp, "Authorization": f"Bearer {scan_token}"}, json=init_body)
    check("initialize com token → não 401/403", r_init.status_code not in (401, 403))

    # tools/call de scan com token só-leitura → 403 insufficient_scope
    r403 = sc.post("/mcp", headers={**hdr_mcp, "Authorization": f"Bearer {read_token}"}, json=call_scan)
    check("scan com scope read → 403", r403.status_code == 403)
    check("403 = insufficient_scope", "insufficient_scope" in r403.text)

    # tools/call de scan com token de scan → middleware libera (não 401/403)
    r_ok = sc.post("/mcp", headers={**hdr_mcp, "Authorization": f"Bearer {scan_token}"}, json=call_scan)
    check("scan com scope scan → liberado (não 401/403)", r_ok.status_code not in (401, 403))

print("\n[E] Ferramentas registradas + execução real via FastMCP")
mcp = sec.build_mcp()

async def _exercise():
    tools = await mcp.list_tools()
    # executa uma ferramenta de verdade pela camada MCP
    result = await mcp.call_tool("calculate_cvss",
                                 {"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"})
    return tools, result

tools, call_result = asyncio.run(_exercise())
check("12 ferramentas registradas", len(tools) == 12)
names = {t.name for t in tools}
check("inclui review_secure_code e calculate_cvss", {"review_secure_code", "calculate_cvss"} <= names)
# call_tool devolve (content, structured) ou content; procura o 9.8 no payload serializado
payload = json.dumps(call_result, default=lambda o: getattr(o, "__dict__", str(o)))
check("execução real da tool retorna CVSS 9.8", "9.8" in payload)

print("\n[F] Dynamic Client Registration (RFC 7591)")
import base64 as _b64, hashlib as _hl, secrets as _secrets  # noqa: E402
from urllib.parse import urlparse, parse_qs  # noqa: E402

REDIRECT = "http://localhost:9876/callback"
reg = as_client.post("/register", json={
    "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none",
    "grant_types": ["authorization_code", "refresh_token"],
    "scope": "security:scan security:read offline_access", "client_name": "Claude Code (e2e)",
})
check("DCR 201", reg.status_code == 201)
dcr = reg.json()
public_client_id = dcr.get("client_id", "")
check("client público sem secret", "client_secret" not in dcr and public_client_id.startswith("dcr-"))

print("\n[G] Authorization Code + PKCE")
verifier = _secrets.token_urlsafe(48)
challenge = _b64.urlsafe_b64encode(_hl.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

# consent page
authz = as_client.get("/oauth/authorize", params={
    "response_type": "code", "client_id": public_client_id, "redirect_uri": REDIRECT,
    "code_challenge": challenge, "code_challenge_method": "S256",
    "scope": "security:scan offline_access", "state": "xyz", "resource": RESOURCE,
})
check("consent 200 (login form)", authz.status_code == 200 and "Senha" in authz.text)
check("sem SSO configurado → sem botão SSO", "Entrar via SSO" not in authz.text)

# credenciais do usuário dev seedado pelo user store (AS_DEV_USER/AS_DEV_PASSWORD)
DEV_USER, DEV_PASS = "dev", "dev-password-change-me"

# login com senha ERRADA → 401, sem code
bad_login = as_client.post("/oauth/authorize", data={
    "client_id": public_client_id, "redirect_uri": REDIRECT, "code_challenge": challenge,
    "resource": RESOURCE, "scope": "security:scan offline_access", "state": "xyz",
    "username": DEV_USER, "password": "senha-errada", "decision": "approve",
}, follow_redirects=False)
check("login senha errada → 401 sem code", bad_login.status_code == 401 and "inválidos" in bad_login.text)

# aprova com login correto → 302 com code no Location
approve = as_client.post("/oauth/authorize", data={
    "client_id": public_client_id, "redirect_uri": REDIRECT, "code_challenge": challenge,
    "resource": RESOURCE, "scope": "security:scan offline_access", "state": "xyz",
    "username": DEV_USER, "password": DEV_PASS, "decision": "approve",
}, follow_redirects=False)
loc = approve.headers.get("location", "")
q = parse_qs(urlparse(loc).query)
check("login OK → 302 com code+state", approve.status_code == 302 and "code" in q and q.get("state") == ["xyz"])
auth_code = q.get("code", [""])[0]

# troca code+verifier por tokens
tok2 = as_client.post("/oauth/token", data={
    "grant_type": "authorization_code", "code": auth_code, "redirect_uri": REDIRECT,
    "client_id": public_client_id, "code_verifier": verifier,
})
check("token (authorization_code) 200", tok2.status_code == 200)
tj = tok2.json()
check("access_token + refresh_token emitidos", "access_token" in tj and "refresh_token" in tj)
# valida o access token no validador do Security
pj = validator.validate(tj["access_token"])
check("access token do authcode → subject user:dev", pj.subject == "user:dev")
refresh1 = tj["refresh_token"]

# PKCE negativo: code novo, verifier errado (login correto para chegar até o code)
verifier2 = _secrets.token_urlsafe(48)
challenge2 = _b64.urlsafe_b64encode(_hl.sha256(verifier2.encode()).digest()).rstrip(b"=").decode()
as_client.get("/oauth/authorize", params={"response_type": "code", "client_id": public_client_id,
    "redirect_uri": REDIRECT, "code_challenge": challenge2, "scope": "security:scan",
    "state": "s2", "resource": RESOURCE})
appr2 = as_client.post("/oauth/authorize", data={"client_id": public_client_id, "redirect_uri": REDIRECT,
    "code_challenge": challenge2, "resource": RESOURCE, "scope": "security:scan", "state": "s2",
    "username": DEV_USER, "password": DEV_PASS, "decision": "approve"}, follow_redirects=False)
code2 = parse_qs(urlparse(appr2.headers.get("location", "")).query).get("code", [""])[0]
bad = as_client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code2,
    "redirect_uri": REDIRECT, "client_id": public_client_id, "code_verifier": "verifier-errado"})
check("PKCE errado → invalid_grant", bad.status_code == 400 and "invalid_grant" in bad.text)

print("\n[H] Refresh token com rotação (single-use)")
ref = as_client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh1})
check("refresh 200 + novo access", ref.status_code == 200 and "access_token" in ref.json())
refresh2 = ref.json().get("refresh_token", "")
check("refresh rotacionado (token novo)", refresh2 and refresh2 != refresh1)
reuse = as_client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh1})
check("reuso do refresh antigo → invalid_grant", reuse.status_code == 400 and "invalid_grant" in reuse.text)

print("\n[I] Federação OIDC upstream — unidades puras + validação de id_token")
import time as _time  # noqa: E402
import jwt as _jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa as _rsa  # noqa: E402
from cryptography.hazmat.primitives import serialization as _ser  # noqa: E402

up = AS.UpstreamOIDC(
    enabled=True, name="Keycloak", issuer="https://idp.example/realms/x",
    client_id="mcp-as", redirect_uri="https://mcp.suaempresa.com/auth/oauth/sso/callback",
    scopes="openid email", authorization_endpoint="https://idp.example/authorize",
    role_claim="groups", role_map={"mcp-admins": "admin", "mcp-devs": "developer"}, default_role="user")

check("from_env desabilitado sem config", AS.UpstreamOIDC.from_env().enabled is False)

# builder puro com state/nonce/PKCE
url = up.build_authorization_url(state="rid123", nonce="n0", code_challenge="chal0")
check("URL OIDC com state/nonce/PKCE S256", all(x in url for x in (
    "https://idp.example/authorize?", "response_type=code", "client_id=mcp-as",
    "state=rid123", "nonce=n0", "code_challenge=chal0", "code_challenge_method=S256")))

# map_identity: claim de grupo → role
ident = up.map_identity({"sub": "u1", "email": "u1@x", "groups": ["mcp-admins"]})
check("map_identity mapeia grupo→role admin", ident["role"] == "admin" and ident["sub"] == "u1")
ident2 = up.map_identity({"sub": "u2", "groups": ["outros"]})
check("map_identity usa default_role", ident2["role"] == "user")

# validate_id_token com chave RSA de teste (nonce certo/errado)
_k = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
_priv = _k.private_bytes(_ser.Encoding.PEM, _ser.PrivateFormat.PKCS8, _ser.NoEncryption()).decode()
_pub = _k.public_key().public_bytes(_ser.Encoding.PEM, _ser.PublicFormat.SubjectPublicKeyInfo).decode()
_now = _time.time  # evita Date.now proibido? não — estamos em Python normal
_claims = {"iss": up.issuer, "aud": up.client_id, "sub": "jdoe", "nonce": "NONCE1",
           "groups": ["mcp-devs"], "exp": int(_time.time()) + 300, "iat": int(_time.time())}
_idt = _jwt.encode(_claims, _priv, algorithm="RS256")
ok_claims = up.validate_id_token(_idt, expected_nonce="NONCE1", signing_key=_pub)
check("id_token válido (nonce ok) → claims", ok_claims["sub"] == "jdoe")
try:
    up.validate_id_token(_idt, expected_nonce="ERRADO", signing_key=_pub)
    check("nonce errado → OIDCError", False)
except AS.OIDCError:
    check("nonce errado → OIDCError", True)

print("\n[J] Fluxo federado completo no auth-mcp (SSO start→callback→code→token)")
from urllib.parse import parse_qs as _pq, urlparse as _up_parse  # noqa: E402
AS.UPSTREAM = up  # habilita SSO no AS (duck-typing)

# cliente inicia authorize com SEU PKCE
fed_verifier = _secrets.token_urlsafe(48)
fed_challenge = _b64.urlsafe_b64encode(_hl.sha256(fed_verifier.encode()).digest()).rstrip(b"=").decode()
authz2 = as_client.get("/oauth/authorize", params={
    "response_type": "code", "client_id": public_client_id, "redirect_uri": REDIRECT,
    "code_challenge": fed_challenge, "scope": "security:scan offline_access",
    "state": "fed1", "resource": RESOURCE})
check("consent mostra botão SSO quando habilitado", "Entrar via SSO" in authz2.text)
import re as _re  # noqa: E402
m = _re.search(r"/oauth/sso/start\?rid=([A-Za-z0-9_\-]+)", authz2.text)
rid = m.group(1) if m else ""
check("rid presente no link SSO", bool(rid))

# start → 302 para o IdP com state=rid, nonce e code_challenge
start = as_client.get("/oauth/sso/start", params={"rid": rid}, follow_redirects=False)
sloc = start.headers.get("location", "")
check("sso/start → 302 ao IdP com nonce+PKCE", start.status_code == 302
      and "https://idp.example/authorize?" in sloc and f"state={rid}" in sloc
      and "nonce=" in sloc and "code_challenge=" in sloc)

# monkeypatch da troca upstream (evita rede real); identidade federada com role admin
async def _fake_exchange(code, *, code_verifier, expected_nonce):
    return {"sub": "jdoe", "email": "jdoe@x", "role": "admin", "groups": ["mcp-admins"]}
up.exchange_and_validate = _fake_exchange

cb = as_client.get("/oauth/sso/callback", params={"code": "idp-code", "state": rid}, follow_redirects=False)
fed_code = _pq(_up_parse(cb.headers.get("location", "")).query).get("code", [""])[0]
check("callback federado → 302 com code do auth-mcp", cb.status_code == 302 and bool(fed_code))

# troca o code do auth-mcp pelo access token (com o PKCE do cliente)
fed_tok = as_client.post("/oauth/token", data={
    "grant_type": "authorization_code", "code": fed_code, "redirect_uri": REDIRECT,
    "client_id": public_client_id, "code_verifier": fed_verifier})
check("token federado 200", fed_tok.status_code == 200)
fed_claims = validator.validate(fed_tok.json()["access_token"]).raw_claims
check("token federado → subject oidc:jdoe + role admin",
      fed_claims.get("sub") == "oidc:jdoe" and fed_claims.get("role") == "admin")

print(f"\n===== {len(PASS)} PASS / {len(FAIL)} FAIL =====")
if FAIL:
    print("FALHAS:", FAIL); sys.exit(1)
print("E2E OK")
