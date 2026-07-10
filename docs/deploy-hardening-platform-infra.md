# Deploy hardening dos MCP sidecars → platform-infra

> **Escopo:** requisitos de deploy/K8s dos 20 MCP sidecars (Model-C `mcp_http`) que
> **não** vivem no código do sidecar e pertencem ao repositório **platform-infra**
> (onde deploy/HML mora, decisão de arquitetura 2026-07-09). Referências normativas:
> `STD-DEPLOY-001` (container/K8s hardening), `STD-MCP-001` CI-10 (network no-bypass),
> `STD-SEC-006` (INV-1). O código do sidecar (PEP inner-token, `/v1/health`, non-root
> Dockerfile, registro declarativo) **já está conforme** no platform-devs.

## Por que aqui não

A postura de segurança do Model-C **não** depende só do inner token — ela depende do
**controle de rede**: "token design alone does not prevent bypass — the network is the
control (INV-1)". Isso é K8s/Istio, logo platform-infra.

## Requisitos por sidecar (`platform-<ns>`, porta 7100)

### 1. NetworkPolicy — ingress só do gateway (STD-MCP-001 CI-10 / INV-1)
- `default-deny` de ingress; **permitir ingress apenas** do pod do gateway
  (`app: platform-twin-gateway` / namespace `platform-mcp`) na porta `7100`.
- Egress allowlist explícito (JWKS do admin, DB do próprio sidecar quando stateful).

### 2. Istio AuthorizationPolicy — mTLS STRICT + SPIFFE
- mTLS `STRICT`.
- `principals: ["cluster.local/ns/platform-mcp/sa/platform-twin-gateway"]` — só a
  ServiceAccount do gateway pode chamar `/mcp/tools/call`.

### 3. K8s securityContext (STD-DEPLOY-001)
- `runAsNonRoot: true`, `runAsUser: 1000` (a imagem já roda non-root UID 1000).
- `readOnlyRootFilesystem: true` + `emptyDir` em `/tmp`.
- `capabilities.drop: [ALL]`, `allowPrivilegeEscalation: false`, seccomp `RuntimeDefault`.
- `automountServiceAccountToken: false`.

### 4. Probes
- liveness/readiness/startup → `:7100/v1/health` (o sidecar mcp_http expõe `/v1/health`;
  o split `:9090 /health/live+ready` do STD-SEC-001 é do **app REST**, não do sidecar).

### 5. Imagem / supply-chain (STD-DEPLOY-001 / STD-CICD-001)
- **Dockerfile multi-stage** (hoje é single-stage).
- **Base image pinada por digest** `python:3.12-slim@sha256:...` (hoje só por tag).
- **Hash-pinning / lockfile** das deps (hoje `pip install .` sem lock).
- Deploy por **digest SHA256 imutável**, nunca tag mutável; HPA 2–10, PDB `minAvailable:1`.

### 6. Config dos 8 stateful (achado da prova de uso real)
- `audit, config, deploy, docs, pipeline, qa-mcp, services, test` conectam PG **eagermente**
  no boot; o default `pg_host="claude-dev"` não resolve. Setar `PG_HOST` (ex.:
  `dataforall-tenant-postgres`, db `app`) + a senha via **Vault** (o código já degrada p/ env).

## O que JÁ está pronto no platform-devs (não refazer)
- Dockerfile non-root UID 1000 + `HEALTHCHECK :7100/v1/health` + `.dockerignore` (segredos fora).
- Registro declarativo pull-based (`gateway/` entry.json + gateway-mapping.sql idempotente).
- PEP inner-token RS256/JWKS/aud/jti fail-closed; `enforce_security_invariants()` no boot.
