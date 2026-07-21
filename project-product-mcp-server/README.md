# Platform Project Product

Serviço Trinity canônico do domínio de portfólio:

- `app/`: FastAPI `/api/v1` e adaptador privado `/api/internal/mcp`;
- `src/platform_project_product/`: contratos e cliente tipado reutilizável;
- `mcp/project_product_mcp/`: sidecar MCP HTTP-only, sem acesso ao banco;
- `alembic/`: schema versionado para PostgreSQL e MySQL 8.4 por tenant;
- `deploy/`: perfil, stack Swarm, migration job e action classes de governança.

## Dados e tenancy

O serviço é stateful e aceita stores de tenant PostgreSQL ou MySQL 8.4. `DB_ENGINE` seleciona a validação de tenancy e o casing do runtime (`postgresql` ou `mysql`), enquanto host, database, usuário, credencial e engine efetivo de cada migration continuam resolvidos em `ADMIN_DATAFORALL.PLATFORMS`. O código passa apenas `tenant_id` para `platform-database-lib`; não há SQLite, DSN de tenant em variável do serviço ou migration no startup.

PostgreSQL usa schema por tenant e tabelas lowercase. MySQL usa database por tenant e tabelas UPPERCASE. A mesma revision Alembic é compilada pelo dialeto canônico; locks são `pg_advisory_xact_lock` no PostgreSQL e `GET_LOCK`/`RELEASE_LOCK` no MySQL. Em um deployment da API, `DB_ENGINE` deve corresponder à família de tenant atendida naquele runtime; o job de migration pode processar tenants das duas engines porque lê o engine de cada registro do registry.

As tabelas `portfolio_products`, `portfolio_projects` e `portfolio_project_repository_bindings` usam isolamento físico do tenant mais `id_environment`/`id_owner`, auditoria canônica, soft-delete, idempotência e versão otimista. Repositórios externos são referências opacas e neutras de provider; credenciais e operações Git continuam em `platform-connectors`.

## Integrações

- usuários: referências opacas de `platform-admin`;
- policy/HITL: `platform-governance` antes de toda tool MCP;
- repositórios: `connector_ref` e `repository_ref` de `platform-connectors`;
- agenda, comunicação e notificação: `service_refs` para `platform-scheduler`, `platform-communication` e `platform-notification`.

O sidecar revalida o inner token RS256 para a audiência `mcp:portfolio`, derivada das capabilities `portfolio.*` pelo exchange canônico. O `tenant_id` textual vem exclusivamente do token; o portfólio usa o escopo interno tenant-global `id_environment=0` e nunca aceita seleção de ambiente do chamador. Em seguida aplica rate limit compartilhado, PEP remoto fail-closed e encaminha somente para a API privada com token S2S. Local e remoto usam o mesmo contrato HTTP.

## Observabilidade e proteção operacional

A API expõe apenas liveness, readiness e métricas autenticadas na porta de management `:9090`; as rotas de negócio permanecem na porta `:8000`. Logs estruturados, OTEL e Sentry seguem as bibliotecas do template. API e MCP usam limites explícitos de requisição/resposta e rate limiting compartilhado em Redis, sem fallback em memória no perfil cloud.

## Execução local

Defina as variáveis documentadas em `docs/env.reference.md` e execute:

```powershell
python -m scripts.migrate
python -m app.main
$env:PYTHONPATH = ".;src;mcp"
python -m project_product_mcp.server.mcp_server
```

Ou use `docker compose up platform-project-product-api project-product-mcp redis`. O MCP fica em `:27121`; a API em `:28001`; management em `:29091`.

## Release

1. construir e testar uma imagem imutável;
2. executar `python -m scripts.migrate` como job isolado com a mesma imagem;
3. bloquear a promoção se qualquer tenant falhar;
4. materializar as action classes e permissões de `deploy/governance-action-classes.yaml` no tenant;
5. aplicar `deploy/stack.yaml` por digest;
6. validar `/v1/ready` e os contratos MCP.

GitHub Actions não faz parte deste fluxo.

O build canônico exige BuildKit e o secret `github_token`, usado apenas no stage builder para reescrever dependências privadas SSH para HTTPS autenticado:

```powershell
docker build --secret id=github_token,env=TOKEN_GITHUB -f project-product-mcp-server/Dockerfile .
```
