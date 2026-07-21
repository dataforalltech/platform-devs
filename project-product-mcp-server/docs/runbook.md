# Runbook

- Liveness API: `:9090/health/live`; readiness consulta registry e o store real do tenant (PostgreSQL ou MySQL) em `:9090/health/ready`.
- Métricas API: `:9090/metrics`, sempre com `Authorization: Bearer <METRICS_SCRAPE_TOKEN>`; não exponha a porta de management publicamente.
- Liveness MCP: `:7121/v1/health`; readiness real: `:7121/v1/ready` (API, JWKS, governance e rate limit); tools list em `/mcp/tools/list`.
- Saturação/abuso: correlacione `429` por tenant, ator e tool com Redis; cloud deve falhar fechado se o backend de rate limit estiver indisponível.
- Telemetria: valide exportação OTLP e Sentry sem incluir tokens, payloads de tool ou referências opacas em atributos/eventos.
- `503` do PEP indica indisponibilidade de `platform-governance`; não há fallback permissivo.
- `409 approval_required` traz `approvalUid` e `checkpointUid` criados em governance.
- Falha de tenant deve ser investigada em `PLATFORMS`; nunca injete um DSN alternativo.
- Migration é somente o job `python -m scripts.migrate`; nunca reinicie réplicas para tentar DDL.
