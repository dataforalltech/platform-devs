# Fase 1 — Migração de autz para `platform_governance.TwinPep` (piloto: security)

**Status:** Plano concreto (verificado contra o código real) · **Date:** 2026-07-05 · **Authors:** caiog
**Relacionado:** `MCP_ADR_INDEX.md`, ADR-004 (Twin Token), ADR-005 (PEP/PDP)
**Método:** assinaturas e contratos foram **verificados adversarialmente** contra `platform-governance` e
`platform-admin` (workflow `phase1-twinpep-lean`); as correções da verificação estão embutidas.

---

## 0. Premissa que encolhe o escopo (fato verificado)

O **gateway central (`platform-mcp`) é o único que chama `/api/v1/twin/exchange`** (evidência:
`platform-admin/app/exchange/client.py`). O **MCP de serviço (security) NÃO emite nem troca token** — ele
**apenas VALIDA o inner token** (`aud=mcp:security`, RS256, JWKS do platform-admin) e **enforça capability/
scope via `TwinPep`**. Logo, a Fase 1 do piloto é **pequena e local**:

```
[fora do MCP]  cliente → front-door OAuth → /twin/sessions (admin, aud=mcp:gateway)
               → gateway → /twin/exchange (admin) → inner token (aud=mcp:security, TTL 60s)
[no MCP]       security recebe o inner token → TwinPep.enforce(capability, required_scope) → executa a tool
```
Emissão/exchange/front-door são responsabilidade de admin+gateway (ADR-004 D4.6/D4.7), **fora deste diff**.

---

## 1. Abordagem de integração

**Manter** o que já temos no transporte e no middleware; **trocar apenas a decisão de autz.**

- **FastMCP (DevTeam, ex. security):** manter o `BearerAuthMiddleware` (ASGI) que já espia o `tool name` no
  corpo JSON-RPC e re-injeta o corpo (`_replay_receive`). Trocar a **decisão** de
  `JwtValidator + Principal.has_scope` por **`await TwinPep.enforce(request, capability=…, required_scope=…)`**.
- **Legados (`mount_lowlevel_streamable_http`):** como já têm um `dispatch` explícito, preferir o
  **`GuardedToolRegistry.register/dispatch`** (mais idiomático que o middleware). Fase 1 foca no FastMCP.

### Assinaturas reais (verificadas — `platform-governance/src/platform_governance/policy/`)
```python
# service_pep.py
TwinPep(*, jwks_url: str | None = None, audience: str, pdp: PDP | None = None,
        verifier: TwinTokenVerifier | None = None, hilt_floor_domains: list[str] | None = None,
        governance_url: str | None = None, governance_token: str | None = None,
        owner_service: str | None = None, tenant_id_default: str = "1")

async TwinPep.enforce(request: starlette.Request, *, capability: str, arguments: dict | None = None,
                      resource_type: str | None = None, required_scope: str | None = None,
                      domain: str | None = None) -> TwinClaims
# lê o token de: Authorization: Bearer  →  X-Twin-Token  →  params._meta.twin_token
# exceções: TwinTokenError (401) · PolicyDenied (403) · PolicyPending (409)
```

---

## 2. Diff antes/depois

### 2.1 `shared/mcp_auth.py` — nova classe `TwinPepMiddleware` (ao lado do `BearerAuthMiddleware`)

**Antes** (decisão bespoke, dentro de `BearerAuthMiddleware.__call__`):
```python
principal = await anyio.to_thread.run_sync(self._authenticate, auth_header)  # JwtValidator
required = self._required_scope(body)                                        # scope_for_request(tool)
if not principal.has_scope(required):
    await self._forbidden(send, required); return
```

**Depois** (delegar ao PEP mandatório; manter body-peek + `_replay_receive`):
```python
from starlette.requests import Request

class TwinPepMiddleware:
    """Enforça platform_governance.TwinPep por ferramenta num app Streamable HTTP (FastMCP)."""
    def __init__(self, app, *, twinpep, capability_for, prm_url,
                 public_paths=("/v1/health", "/health", "/.well-known/"), protected_prefix="/mcp"):
        self.app = app; self.twinpep = twinpep; self.capability_for = capability_for
        self.prm_url = prm_url; self.public_paths = tuple(public_paths); self.protected_prefix = protected_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if self._is_public(path) or not path.startswith(self.protected_prefix):
            return await self.app(scope, receive, send)

        body = b""
        if scope["method"] == "POST":
            body = await Request(scope, receive).body()          # body-peek (reaproveitado)
        method, tool = _peek_jsonrpc(body)                        # helper: (method, params.name)
        cap, req_scope, resource_type = self.capability_for(method, tool)  # None em initialize/tools/list

        if cap is not None:                                       # só tools/call é enforçado
            request = Request(scope, _replay_receive(body, receive))  # Request p/ o TwinPep ler o token
            try:
                claims = await self.twinpep.enforce(
                    request, capability=cap, required_scope=req_scope, resource_type=resource_type)
            except TwinTokenError as e:
                return await self._challenge(send, 401, "invalid_token", str(e))
            except PolicyDenied as e:
                return await self._challenge(send, 403, "forbidden", str(e))
            except PolicyPending as e:
                return await self._challenge(send, 409, "approval_required", str(e))
            scope["state"] = scope.get("state", {}); scope["state"]["twin_claims"] = claims

        await self.app(scope, _replay_receive(body, receive), send)  # re-injeta o corpo (SSE não aborta)
```
> **Nota (correção da verificação):** `enforce` é `async`, mas o resolver de JWKS padrão (`JwksKeyResolver` →
> `PyJWKClient`) faz **fetch HTTP bloqueante no primeiro uso**. Como não dá para `to_thread` um coroutine,
> **pré-aqueça o JWKS no startup** (ver §3) para o primeiro `enforce` não travar o event loop.

**Remover do piloto (não usados após a troca):** o caminho `JwtValidator`/`Principal.has_scope`/
`StaticTokenStore` do fluxo do MCP de serviço (emissão/validação OAuth é do front-door, fora do MCP).
`_peek_jsonrpc` e `_replay_receive` **permanecem**.

### 2.2 `security-mcp-server/src/server/mcp_server.py` — `build_app`

**Antes:**
```python
if validators is None:
    validators = [JwtValidator(issuer=AS_ISSUER, audience=RESOURCE, jwks_url=AS_JWKS_URL).validate]
return BearerAuthMiddleware(app, resource_metadata_url=..., validators=validators,
                            scope_for_request=_scope_for_request)
```

**Depois:**
```python
from platform_governance.policy import TwinPep   # dep nova

def build_app(twinpep=None):
    mcp = build_mcp(); app = mcp.streamable_http_app()   # + custom_route /v1/health e PRM (inalterado)
    if twinpep is None:
        twinpep = TwinPep(jwks_url=os.environ["URL_ADMIN_TWIN_JWKS"], audience="mcp:security")
        # HILT (opcional): TwinPep(..., hilt_floor_domains=["security"], governance_url=..., governance_token=...)
    return TwinPepMiddleware(app, twinpep=twinpep, capability_for=_capability_for, prm_url=RESOURCE_METADATA_URL)
```

### 2.3 Mapa `SCOPE_FOR_TOOL` → `(capability, required_scope, resource_type)`
`capability` segue a convenção da plataforma `<domínio>.<recurso>.<verbo>` (confirmada no governance):
```python
def _capability_for(method, tool):
    if method != "tools/call" or not tool:
        return (None, None, None)                 # initialize/tools/list passam sem enforce
    return _CAP_MAP.get(tool, ("security.tool.use", "security:read", "tool"))

_CAP_MAP = {
  "review_secure_code":        ("security.scan.review",  "security:scan",  "scan"),
  "scan_secrets":              ("security.scan.secrets", "security:scan",  "scan"),
  "scan_dependency_risks":     ("security.scan.deps",    "security:scan",  "scan"),
  "calculate_cvss":            ("security.calc.cvss",    "security:read",  "calc"),
  "harden_headers":            ("security.calc.headers", "security:read",  "calc"),
  "check_password_policy":     ("security.calc.pwpolicy","security:read",  "calc"),
  "analyze_compliance":        ("security.calc.compliance","security:read","calc"),
  "map_attack_surface":        ("security.calc.surface", "security:read",  "calc"),
  "generate_threat_model":     ("security.model.threat", "security:model", "model"),
  "generate_security_controls":("security.model.controls","security:model","model"),
  "generate_incident_response_plan":("security.model.irplan","security:model","model"),
  "status":                    ("security.status.read",  "security:read",  "status"),
}
```

---

## 3. Deps, env e startup

- **Dep (pyproject):** `platform-governance` (via git privado/wheel, versão pinada — ex.
  `platform-governance @ git+ssh://git@github.com/dataforalltech/platform-governance.git@v1.0.2`). O
  Dockerfile precisa do secret de acesso a repos privados (padrão já usado em outros repos).
- **Env:** `URL_ADMIN_TWIN_JWKS` (ex. `https://<admin>/api/v1/twin/jwks.json` — **não** hardcodar host/porta;
  correção da verificação), e a audiência `mcp:security` (constante no código ou env).
- **Startup (pré-aquecer JWKS — mitigação do bloqueio):** no lifespan do app, disparar uma resolução de chave
  do verifier uma vez (fetch do JWKS) para que o primeiro `enforce` não faça I/O bloqueante no event loop.
- **Remover no piloto:** dependência do nosso `auth-mcp` como validador do MCP; `JwtValidator` do caminho do
  MCP. (`oauth_store`/`user_store`/`oidc_upstream` são do front-door — descontinuados conforme ADR-003/004,
  fora deste diff.)

---

## 4. Plano de verificação (sem subir a plataforma inteira)

Emitir um **twin token de teste** assinado com uma chave RSA local e injetar um verifier com chave estática —
`TwinPep` valida offline, então dá para testar `allow/deny/scope/HILT` in-process com `TestClient`:
```python
from platform_governance.policy import TwinPep, TwinTokenVerifier, StaticKeyResolver
# CORREÇÃO (verificação): StaticKeyResolver recebe um DICT {kid: chave}, não (kid=, key=)
verifier = TwinTokenVerifier(StaticKeyResolver({"test-kid": pub_pem}), audiences=["mcp:security"])
pep = TwinPep(audience="mcp:security", verifier=verifier)          # sem jwks_url → não faz HTTP
app = build_app(twinpep=pep)
```
Casos:
1. **Sem token** → `/mcp` tools/call → `TwinTokenError` → **401** (+ WWW-Authenticate).
2. **Token válido + scope certo** (twin token de teste: `token_use=twin`, `aud=mcp:security`,
   `scopes=[security:scan]`, `act.sub=agent:test`) → tool executa.
3. **Scope insuficiente** (token só `security:read` numa tool `security:scan`) → `PolicyDenied` → **403**.
4. **HILT** (opcional; exige PDP com floor + `governance_url`) → `PolicyPending`/`enforce_or_park` → **409**.
5. **initialize/tools/list** passam sem enforce.

Reaproveitar o harness anti-shadow de `tests/e2e/test_oauth_security_pilot.py` (registrar `shared`/`src` por
caminho; TestClient como context manager para o lifespan do Streamable HTTP).

---

## 5. Checklist ordenado (piloto security)
1. Adicionar dep `platform-governance` ao `pyproject.toml` + secret de build no Dockerfile.
2. `shared/mcp_auth.py`: adicionar `TwinPepMiddleware` (§2.1); manter `_peek_jsonrpc`/`_replay_receive`.
3. `security` `mcp_server.py`: `_CAP_MAP` + `_capability_for`; `build_app` usando `TwinPepMiddleware` (§2.2/2.3).
4. Lifespan: pré-aquecer JWKS (§3).
5. Env `URL_ADMIN_TWIN_JWKS` + audiência `mcp:security`.
6. Testes in-process (§4) — verifier com `StaticKeyResolver({kid: pub})`.
7. Atualizar o gate DoD (`scripts/check_mcp_dod.py`) p/ aceitar `TwinPep`/`GuardedToolRegistry` como o marcador
   de autz migrada (hoje ele procura `BearerAuthMiddleware`).

## 6. Esforço e riscos
- **Piloto (security):** baixo — troca ~40 linhas de decisão + `_CAP_MAP` + testes. 0.5–1 dia.
- **Generalização (21 MCPs):** mecânica e paralelizável — cada DevTeam: `_CAP_MAP` + trocar middleware; cada
  legado: `GuardedToolRegistry` no dispatch. ~2–4 dias com fan-out.
- **Riscos / correções embutidas:**
  - **JWKS bloqueante:** `enforce` é async mas o resolver padrão bloqueia no 1º fetch → **pré-aquecer no startup**.
  - **`StaticKeyResolver({kid: key})`** (dict), não `(kid=, key=)`.
  - **HILT:** `enforce()` levanta `PolicyPending` **sem** `checkpoint_uid`; para 409 com refs de aprovação use
    `enforce_or_park()` + `governance_url`/`governance_token`.
  - **`URL_ADMIN_TWIN_JWKS`** por env (host/porta não hardcodados).
  - **Dependência de dados:** o PDP avalia scope/purpose/mandate a partir do `policy_store` do governance —
    as capabilities/purposes do security precisam existir lá para `allow` real (coordenar com governance).
  - **Front-door OAuth (ADR-004 D4.7)** é track separado — não bloqueia esta Fase 1 (o MCP só valida o inner token).
