# pipeline-mcp-server

Sidecar MCP (`kind=mcp_http`, **Model C**) que mantém o registro longitudinal do
pipeline DEV→HML→PROD dos microserviços da plataforma dataforalltech. A persona é
**stateful**, tenant-scoped e dual-db: registra pipelines, resultados de gates,
recomendações, aprovações humanas e solicitações de rollback no banco canônico.

O `pipeline-mcp` é **ledger-only e fail-closed**. Ele não observa nem altera GitHub,
não executa lint/testes/scans/builds, não cria ou mergeia PRs, não promove ambientes e
não executa rollback. Toda ação externa ocorre em executor manual controlado, fora
deste serviço, e sua evidência deve ser registrada separadamente. Um comando sugerido,
um booleano de gate ou um registro no ledger não comprovam execução.

Integra-se ao MCP Gateway central conforme:
- `STD-MCP-001` — contrato de integração com o gateway (CI-1..CI-11)
- `STD-SEC-006` — inner Twin Token (audiência `mcp:pipeline-mcp`)
- `STD-SEC-001/004` — RS256 exclusivo, `/docs` desabilitado, segredos fora do código
- `STD-OBS-001` — logging estruturado JSON

## Limite operacional e regras de aprovação

| Solicitação | Comportamento do ledger |
|---|---|
| Revisão de mudança para DEV | apenas recomenda revisão humana a partir dos gates registrados; não consulta PRs |
| `dev` → `homol` | registra recomendação `pending_human_approval`; não cria PR nem altera ambiente |
| `homol` → `prod` | registra recomendação `pending_human_approval`; não cria PR nem altera ambiente |
| Aprovação humana | registra `pending_external_execution`; não mergeia nem promove |
| Rollback | registra solicitação `pending_human_approval`; não altera versão ou ambiente |

Gates ausentes, não avaliados ou sem configuração explícita nunca são considerados
aprovados. Mesmo quando todos os gates registrados passam, `can_promote` permanece
`false`: o resultado é somente uma recomendação para decisão e execução externas.

## Tools (14)

**Pipeline (8):** `register_pipeline`, `get_pipeline`, `list_pipeline`,
`promote_service`, `approve_promotion`, `watch_prs`, `block_service`, `rollback`

**Gates (3):** `add_gate_result`, `get_gate_status`, `clear_gates`

**Histórico/Config (3):** `get_promotion_history`, `get_pipeline_overview`,
`set_pipeline_config`

Semântica das tools que poderiam ser confundidas com execução:

- `promote_service`: valida o ledger e registra uma recomendação pendente de aprovação
  humana; `promoted=false` e `external_action_performed=false`.
- `approve_promotion`: registra quem aprovou e move o registro para
  `pending_external_execution`; não atualiza o ambiente.
- `watch_prs`: nome legado preservado por compatibilidade; não consulta GitHub. Retorna
  recomendações baseadas apenas nos pipelines e gates já registrados.
- `rollback`: registra uma solicitação pendente; `rolled_back=false`.

Cada tool é publicada em `/mcp/tools/list` com os 4 campos de política que o gateway
lê (não deriva por nome): `capability`, `required_scope` (`dominio:tipo:acao`),
`resource_type`, `data_domain`.

## Segurança (Model C)

- **Inner Twin Token obrigatório** em toda execução (`/mcp/tools/call`): re-verificado
  na própria audiência (`mcp:pipeline-mcp`), RS256 via JWKS do platform-admin, `jti`
  obrigatório — fail-closed. Não há tool tokenless.
- **`tenant_id` sempre dos claims** do token verificado, nunca de argumento do cliente
  (SEC-035 / INV-3).
- **`enforce_security_invariants()`** roda no boot (fail-fast): `DOCS_ENABLED=false`,
  audiência `mcp:<namespace>`, e em `RUNTIME_ENV=cloud` exige `URL_ADMIN_TWIN_JWKS` e
  `PG_PASSWORD`.
- **Segredos**: a senha do DB é resolvida por `load_secret` (Vault quando `VAULT_ADDR`
  está setado, com degradação graciosa p/ env). Nenhum default com cara de credencial
  fica no código.

## HTTP sidecar (porta `MCP_PORT`, default 7100)

- `GET  /v1/health` — liveness (sem token)
- `GET  /mcp/tools/list` — catálogo governado (com metadados de policy)
- `POST /mcp/tools/call` — execução (inner token obrigatório)

## Configuração (env vars)

Um único `.env` (STD-SEC-004); ver `.env.example`. Discriminador de ambiente:
`RUNTIME_ENV ∈ {local, cloud}`.

| Variável | Default | Descrição |
|---|---|---|
| `RUNTIME_ENV` | `local` | `local` \| `cloud` |
| `MCP_TWIN_AUDIENCE` | `mcp:pipeline-mcp` | audiência do inner token |
| `URL_ADMIN_TWIN_JWKS` | — | JWKS do platform-admin (obrigatório em cloud) |
| `MCP_PORT` | `7100` | porta do sidecar HTTP |
| `DOCS_ENABLED` | `false` | Swagger nunca exposto |
| `MCP_SERVICE_LOG_LEVEL` | `INFO` | nível de log |
| `DB_ENGINE` | `mysql` | dialeto `mysql` \| `postgresql` |
| `DB_HOST`, `DB_NAME` | — | fallback do backend do tenant |
| `DB_PORT` | `3306` | porta do backend do tenant |
| `DB_USER` | `root` | usuário fallback do backend do tenant |
| `DB_PASSWORD` | — | senha via env/Vault |
| `ADMIN_DB_HOST` | — | host do catálogo `PLATFORMS` (obrigatório em cloud) |
| `ADMIN_DB_PORT` | `3306` | porta do catálogo administrativo |
| `ADMIN_DB_USER` | `root` | usuário do catálogo administrativo |
| `ADMIN_DB_PASSWORD` | — | senha via env/Vault (obrigatória em cloud) |

Não existem credenciais operacionais de GitHub no runtime nem nas tools MCP, porque chamadas e
mutações externas estão fora do contrato. Enquanto as dependências privadas ainda forem resolvidas
por Git, o builder isolado pode receber um token efêmero, read-only e montado como BuildKit secret;
esse material não pode alcançar a imagem final. A política transversal canônica é
`platform-infra/docs/architecture/delivery-without-github-actions.md`.

## Desenvolvimento

```bash
cd pipeline-mcp-server
pip install -e ".[dev]"
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```
