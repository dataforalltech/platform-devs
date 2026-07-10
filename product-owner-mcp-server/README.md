# product-owner-mcp-server

Persona **Product Owner** do DevTeam — sidecar MCP `kind=mcp_http` (Model C),
gateway-ready. Gera artefatos de produto (visão, discovery, backlog, user stories,
handoffs) a partir dos inputs. **Compute-only**: não há backend REST/Trinity nem
banco de dados — as tools são funções puras chamadas diretamente.

## Arquitetura

- **Runtime**: Python 3.12, stdio (MCP) + sidecar HTTP (FastAPI/uvicorn, `:MCP_PORT`, default `7100`).
- **Integração com o gateway** (`platform-mcp-gateway`):
  - `GET /v1/health` — liveness (sem token).
  - `GET /mcp/tools/list` — catálogo governado; cada tool expõe `capability`,
    `required_scope`, `resource_type`, `data_domain` (STD-MCP-001 CI-2).
  - `POST /mcp/tools/call` — execução; re-verifica o **inner Twin Token**
    (`aud=mcp:product-owner-mcp`, RS256 via JWKS do platform-admin) como defense in
    depth (STD-SEC-006). `tenant_id` vem SEMPRE dos claims do token, nunca do
    argumento do cliente (SEC-035 / INV-3).
- **Segurança no boot** (`enforce_security_invariants`): `DOCS_ENABLED=false` em todo
  ambiente (STD-SEC-001), audiência `mcp:<namespace>`, e `URL_ADMIN_TWIN_JWKS`
  obrigatório em `RUNTIME_ENV=cloud`.
- **Observabilidade**: logging estruturado JSON (STD-OBS-001); tokens/segredos nunca logados.

## Tools (17)

### Análise / priorização / mapeamento (`:read`)
- `analyze_product_problem` — estrutura a análise de um problema de negócio.
- `calculate_rice_score` — RICE = (Reach × Impact × Confidence) / Effort.
- `prioritize_backlog` — ordena itens do backlog (desc) com rank.
- `map_product_risks` — classifica riscos nas 4 categorias de Cagan.
- `map_user_journey` — monta a jornada do usuário em stages.
- `map_user_personas` — estrutura personas de usuário.
- `generate_discovery_questions` — perguntas de discovery/validação.

### Geração de artefatos (`:write`)
- `define_mvp_scope` — must/should/could + out-of-scope de um MVP.
- `define_product_metrics` — KPIs e indicadores leading/lagging.
- `define_product_vision` — visão/missão/objetivos/critérios de sucesso.
- `generate_feature_spec` — especificação de uma feature.
- `generate_go_to_market_brief` — brief de Go-To-Market.
- `generate_handoff_to_architecture` — handoff para Arquitetura.
- `generate_handoff_to_design` — handoff para Design.
- `generate_handoff_to_engineering` — handoff para Engenharia.
- `generate_release_plan` — plano de release faseado.
- `generate_user_stories` — user stories + critérios de aceite.

## Configuração

Um único `.env` (STD-SEC-004); veja `.env.example`. Sem segredos de backend (compute-only).

| Variável | Default | Descrição |
|----------|---------|-----------|
| `RUNTIME_ENV` | `local` | `local` ou `cloud` (discriminador de ambiente). |
| `MCP_TWIN_AUDIENCE` | `mcp:product-owner-mcp` | Audiência exata re-verificada no inner token. |
| `URL_ADMIN_TWIN_JWKS` | — | JWKS do platform-admin (obrigatório em cloud). |
| `MCP_PORT` | `7100` | Porta do sidecar HTTP. |
| `DOCS_ENABLED` | `false` | Swagger/OpenAPI — sempre `false`. |
| `MCP_SERVICE_LOG_LEVEL` | `INFO` | Nível de log. |

## Desenvolvimento

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Container: `Dockerfile` (non-root, STD-DEPLOY-001); entrypoint `product-owner-mcp`.
`MCP_HTTP_ONLY=1` sobe só o sidecar HTTP (uso típico atrás do gateway).
