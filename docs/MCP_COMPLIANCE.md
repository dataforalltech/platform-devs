# Compliance dos MCP servers do platform-devs

> **Fonte normativa (um lar):** as regras MUST/SHOULD vivem no hub
> **`platform-service-template/docs/standards/STD-*`**. Este doc **aponta** o padrão
> e lista o checklist — não reescreve a norma. Em divergência, **o standard prevalece**.

## Padrão canônico

Os MCP servers deste repo (as personas DevTeam) são **sidecars `kind=mcp_http` (Model C)**
agregados pelo `platform-mcp-gateway`. O padrão é definido em:

| Standard (hub) | O quê |
|---|---|
| **STD-MCP-001** | Contrato de integração com o gateway (CI-1…CI-11) |
| **STD-SEC-006** | Token Model C: front token (`mcp:gateway`) → inner token (`mcp:<ns>`, 60s, `jti`) |
| **STD-ARCH-001** | Estrutura `src/{config,server,tools}`; tools sync→dict |
| **STD-SEC-001** | JWT **RS256** exclusivo via JWKS |
| **STD-TEN-001** | tenant só das claims (INV-3) — sidecars tenant-bound |
| **STD-DEPLOY-001** | Dockerfile non-root, healthcheck |
| **STD-CICD-001 / STD-QA-001** | `lint-mcp` + `test-mcp` (cobertura ≥ 80% em `src`) + audience-guard |

## ⚠️ Docs locais SUPERSEDED (não seguir)

- **`MCP_SERVICE_STANDARD.md`** (FastMCP Streamable-HTTP + OAuth-PRM) → **SUPERSEDED** pelo
  Model-C `mcp_http` do hub. O FastMCP/OAuth-PRM não é o canônico ("seguir o platform-mcp-gateway"
  = `mcp_http`, que carrega o inner token no `_meta` e habilita o PEP per-hop; `streamable_http`
  não relaya o inner token).
- **`MCP_CONSTRUCTION_GUIDE.md`** (stdio-only) → **DEPRECATED** (contradiz o padrão HTTP-sidecar).

## Checklist de conformidade (por server)

Cada `*-mcp-server/`:
- [ ] `src/config/settings.py` (`NAMESPACE`, `MCP_TWIN_AUDIENCE=mcp:<ns>`, `URL_ADMIN_TWIN_JWKS`, `MCP_PORT=7100`, `DOCS_ENABLED=false`)
- [ ] `src/server/mcp_server.py`: sidecar `mcp_http` (`/v1/health`, `/mcp/tools/list`, `/mcp/tools/call`) + PEP inner-token (RS256/JWKS, `aud` exato, `jti`)
- [ ] `_TOOL_SCHEMAS` com `capability` + `required_scope` (`dom:tipo:acao`) + `resource_type` + `data_domain`; tools sync→dict
- [ ] `_EXEMPT_TOOLS` (só health/status) + `_EXCLUDE_TOOLS` (denylist)
- [ ] `gateway/` — registro declarativo pull-based (`gateway-mapping.sql` + `twin-gateway-services.entry.json`), **nunca** self-register (CI-3)
- [ ] `tests/` — sidecar + tools, cobertura ≥ 80%
- [ ] `Dockerfile` non-root (UID 1000), `python:3.12-slim`, healthcheck `:7100/v1/health`
- [ ] audience consistente (rode `python scripts/ci_assert_audience.py`)

Referência de implementação: **`architecture-mcp-server/`** (piloto). Procedimento de registro:
`platform-service-template/docs/it/IT-006-registrar-servico-no-mcp-gateway.md`.
