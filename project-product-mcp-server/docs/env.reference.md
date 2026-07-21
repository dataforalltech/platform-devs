# Environment reference

Valores secretos abaixo são nomes lógicos: em cloud vêm exclusivamente de Vault; em local podem vir do processo/`.env` gitignored.

| Variável | Superfície | Regra |
|---|---|---|
| `RUNTIME_ENV` | ambas | `local` ou `cloud` |
| `DB_ENGINE` | API | `postgresql` ou `mysql`; controla validação do tenant e casing das tabelas no runtime |
| `ADMIN_DB_HOST/PORT/NAME/USER` | API/job | registry MySQL `ADMIN_DATAFORALL` |
| `ADMIN_DB_PASSWORD` | API/job local | segredo; cloud usa Vault `admin_db_password` |
| `READINESS_TENANT_ID` | API | tenant autorizado usado pelo probe real; UUID no PostgreSQL, identificador seguro no MySQL |
| `JWT_ISSUER/AUDIENCE/JWKS_URL` | API | contrato RS256 do `platform-admin` |
| `INTERNAL_API_TOKEN` | ambas local | S2S; cloud usa Vault `internal_api_token` |
| `SERVICE_BASE_URL` | MCP | URL exata da API privada |
| `SERVICE_READINESS_URL` | MCP | endpoint de readiness real da API na porta de management |
| `SERVICE_ALLOWED_HOSTS` | MCP | allowlist JSON de hosts exatos |
| `GOVERNANCE_BASE_URL` | MCP | URL de `platform-governance` |
| `GOVERNANCE_INTERNAL_TOKEN` | MCP local | cloud usa Vault `governance_internal_token` |
| `MCP_TWIN_ISSUER/AUDIENCE` | MCP | issuer exato e audiência `mcp:portfolio`, coerente com capabilities `portfolio.*` |
| `URL_ADMIN_TWIN_JWKS` | MCP | JWKS do `platform-admin` |
| `RATE_LIMIT_STORAGE_URI` | ambas local | URI Redis compartilhada; cloud usa Vault `rate_limit_storage_uri` |
| `MCP_RATE_LIMIT_REQUESTS` | MCP | máximo por tenant/ator/tool na janela; default `120` |
| `MCP_RATE_LIMIT_WINDOW_SECONDS` | MCP | janela do limite compartilhado; default `60` |
| `MCP_RATE_LIMIT_KEY_PREFIX` | MCP | prefixo Redis isolado do serviço |
| `MCP_RATE_LIMIT_CONNECT_TIMEOUT_SECONDS` | MCP | timeout de Redis; default `2.0` |
| `METRICS_ENABLED` | API | habilita endpoint Prometheus na porta de management |
| `METRICS_SCRAPE_TOKEN` | API local | bearer obrigatório em `/metrics`; cloud usa Vault `metrics_scrape_token` |
| `OTEL_TRACES_ENABLED` | API | habilita exportação de traces; default `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | API | endpoint do collector OTLP |
| `SENTRY_DSN` | API local | DSN opcional; cloud usa Vault `sentry_dsn` |
| `SENTRY_TRACES_SAMPLE_RATE` | API | amostragem entre `0.0` e `1.0` |
| `TRUSTED_PROXIES` | API | lista JSON de proxies confiáveis |
| `LOG_LEVEL/LOG_TEMP_FOLDER` | API | nível e diretório temporário, sem persistência de domínio |
| `VAULT_ADDR/VAULT_AUTH_METHOD` | cloud | bootstrap por identidade de workload |

Os limites da API são definidos por rota conforme o risco (`30`, `60` ou `200/minute`), não por uma variável global. `DB_ENGINE` não fornece conexão nem substitui o registry: credenciais, host, porta, database e o engine efetivo de cada tenant vêm de `PLATFORMS`. O portfólio é tenant-global: o MCP fixa internamente `id_environment=0` depois de validar o Twin e ignora qualquer `X-Environment-Id`. Não existem `PROJECT_PRODUCT_DB_PATH`, SQLite ou credenciais de tenant configuráveis pelo serviço.
