# security-mcp-server

Sidecar MCP (`kind=mcp_http`, **Model C** — inner Twin Token) da persona de segurança
do DevTeam. **Compute-only**: analisa/gera artefatos de segurança a partir dos inputs,
sem backend REST/Trinity — as tools são funções puras chamadas diretamente.

Integração com o **MCP Gateway central** (`platform-mcp`) conforme
`STD-MCP-001` (contrato de integração) e `STD-SEC-006` (token Model C / inner token).
O gateway verifica o front token; este server re-verifica o **inner Twin Token**
(`aud=mcp:security-mcp`, RS256 via JWKS do platform-admin) — defense in depth.

## Transporte

- **stdio** (MCP primário) + **sidecar HTTP** (`:MCP_PORT`, default `7100`):
  - `GET  /v1/health` — liveness (sem token, CI-7)
  - `GET  /mcp/tools/list` — catálogo governado (capability / required_scope / resource_type / data_domain)
  - `POST /mcp/tools/call` — execução; inner token obrigatório exceto para as tools exemptas
- `MCP_HTTP_ONLY=1` sobe só o sidecar HTTP (uso típico atrás do gateway).

## Tools (12)

Leitura/análise (`:read`): `review_secure_code`, `scan_secrets`, `scan_dependency_risks`,
`calculate_cvss`, `harden_headers`, `check_password_policy`, `analyze_compliance`,
`map_attack_surface`, `status` (tokenless / liveness).

Geração de artefatos (`:write`): `generate_threat_model`, `generate_security_controls`,
`generate_incident_response_plan`.

## Configuração

Um único `.env` (STD-SEC-004), discriminado por `RUNTIME_ENV ∈ {local, cloud}`.
Copie `.env.example` para `.env` e ajuste. Invariantes de segurança (docs off;
`MCP_TWIN_AUDIENCE=mcp:security-mcp`; JWKS obrigatório em cloud) são aplicados
fail-fast no boot por `Settings.enforce_security_invariants()`.

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff format . && python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```
