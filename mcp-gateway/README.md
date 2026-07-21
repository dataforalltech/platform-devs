# MCP Gateway

O gateway é o policy enforcement point HTTP dos MCPs publicados pelo control plane. Ele
autentica o Bearer token, exige tenant verificado, consulta o PDP, aplica rate limit,
troca o token para a audiência do provider, assina o contexto e registra a atividade
antes e depois da execução. Falha de registry, PDP, token exchange, Redis ou ledger
bloqueia a chamada.

## Superfície HTTP

| Método | Endpoint | Responsabilidade |
|---|---|---|
| `GET` | `/v1/health/live` | Confirma que o processo responde |
| `GET` | `/v1/health/ready` | Valida configuração, registry e ledger |
| `GET` | `/mcp` | Lista providers publicados para um ator autenticado |
| `GET` | `/mcp/{provider}/tools` | Lista schemas após delegação autenticada ao provider |
| `POST` | `/mcp/{provider}/tools/call` | Autoriza, audita e encaminha `tools/call` |

O body externo de execução é:

```json
{"id": 1, "name": "tool_name", "arguments": {}}
```

O gateway converte-o para JSON-RPC 2.0 no provider. `tenant_id`, aprovação autodeclarada
e campos que possam transportar segredo são rejeitados nos argumentos.

## Delegação ao provider

Tanto `tools/list` quanto `tools/call` recebem:

- `X-MCP-Context`: contexto codificado com actor, tenant, scopes e correlação;
- `X-MCP-Context-Signature`: HMAC SHA-256 do contexto;
- `X-MCP-Inner-Token`: token trocado para a audiência `mcp:<provider>`.

`tools/call` também exige `policy_decision_id` no contexto. O runtime canônico revalida
assinatura, tenant, scope, decisão e schemas de entrada/saída. A chave de assinatura não
é argumento de tool e deve existir somente no ambiente do gateway e dos providers.

## Configuração obrigatória

O processo não inicia sem todas as variáveis abaixo:

- policy e delegação: `GATEWAY_PDP_URL`, `GATEWAY_TOKEN_EXCHANGE_URL`,
  `GATEWAY_CONTEXT_SIGNING_KEY` e `GATEWAY_RATE_LIMITS_JSON`;
- identidade: `GATEWAY_AS_ISSUER`, `GATEWAY_AS_JWKS_URL` e `GATEWAY_RESOURCE`;
- Redis: `REDIS_HOST`, `REDIS_PORT` e `REDIS_PASSWORD`;
- ledger: `PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER` e `PG_PASSWORD`;
- registry: `MCP_REGISTRY_FILE` apontando para a projeção gerada.

Não há token, role ou limite hardcoded usado como fallback. Valores reais vêm do secret
store ou do ambiente operacional.

## Execução e verificação

Na raiz do repositório:

```powershell
python scripts/validate_mcp_manifests.py
python scripts/generate_mcp_artifacts.py --check
python -m pytest mcp-gateway/tests -q
docker compose config
```

O Compose é gerado de `manifests/mcps/`; edite o manifest e regenere em vez de alterar
`docker-compose.yml` manualmente. PostgreSQL e Redis reais são necessários para o
readiness e para chamadas integradas. A migration
`mcp-gateway/migrations/001_immutable_audit.sql` cria o ledger append-only; a identidade
runtime não deve possuir DDL, `UPDATE`, `DELETE` ou `TRUNCATE`.

## Falhas esperadas

- `401`: Bearer token ou credencial interna do gateway ausente/inválida;
- `403`: tenant, scope, decisão ou aprovação verificada ausente; tool desabilitada;
- `400`: argumentos fora do contrato ou contendo contexto/segredo não confiável;
- `503`: provider, registry, policy, token exchange, rate limit ou ledger indisponível;
- `429`: limite configurado excedido.

Consulte [Control plane MCP](../docs/architecture/mcp-control-plane.md) e
[Runtime e tools publicados](../docs/architecture/mcp-runtime-tools.md).
