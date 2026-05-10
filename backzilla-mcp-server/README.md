# BackZilla — Backend Engineering MCP Server

**BackZilla** é um agente especialista em Backend Engineering, responsável por transformar requisitos, regras de negócio e integrações em APIs seguras, escaláveis, observáveis e fáceis de manter.

## Filosofia

```
PixelFera desenha a experiência.
FrontZilla constrói a interface.
BackZilla sustenta a operação por trás.
```

## Conhecimentos

### Arquitetura
- APIs REST, GraphQL, WebSockets
- Microserviços, modular, Clean Architecture, DDD, Event-driven
- Filas, mensageria, jobs assíncronos
- Cache, rate limiting, circuit breakers

### Linguagens
- Python (FastAPI, Flask)
- Node.js (NestJS, Express)
- TypeScript
- Java / Spring Boot (opcional)
- Go (opcional)

### Dados
- PostgreSQL, MySQL, MongoDB, Redis, BigQuery
- Modelagem relacional e NoSQL
- Migrations, índices, otimização de queries
- Transações, consistência

### Segurança
- JWT, OAuth2, RBAC, IAM
- Criptografia, validação, sanitização
- Logs seguros sem vazar secrets
- OWASP API Security

### Cloud
- Docker, Kubernetes
- AWS (ECS, Lambda, API Gateway, SQS, Secrets Manager)
- GCP (Cloud Run, GKE, Pub/Sub)

## 14 Tools

1. **analyze_backend_requirement** — Análise de requisito de negócio
2. **generate_api_contract** — Geração de contrato de API
3. **generate_fastapi_router** — Router FastAPI completo
4. **generate_nestjs_controller** — Controller NestJS
5. **generate_service_layer** — Serviço com regra de negócio
6. **generate_repository_layer** — Repository com operações CRUD
7. **generate_database_schema** — Schema com índices e constraints
8. **generate_migration** — Migration idempotente e reversível
9. **generate_auth_policy** — Política de autenticação e autorização
10. **generate_backend_tests** — Testes unitários, integração, E2E
11. **review_backend_code** — Revisão de código
12. **optimize_query** — Otimização de queries
13. **generate_openapi_spec** — Especificação OpenAPI
14. **map_integration_flow** — Fluxo de integração com sistemas externos

## Instalação

```bash
cd backzilla-mcp-server
npm install
npm run build
```

## Teste

```bash
npm test
```

## Execução

```bash
npm start
```

## Uso

Acesse via `/mcp` no Claude Code e selecione **backzilla-mcp-server** para acessar todas as 14 tools.

## Slogan

**BackZilla: onde a regra vira API e o caos vira serviço.**
