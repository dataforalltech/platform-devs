# Runtime seguro e tools MCP publicadas

**Status:** implementado  
**Data:** 2026-07-18

## Contrato do runtime

`shared/secure_runtime.py` é o runtime HTTP usado pelos novos providers. Cada tool possui
nome, descrição, JSON Schema de entrada e saída, scope, mutabilidade, risco e handler.
O runtime oferece apenas:

- `GET /v1/health/live` e `GET /v1/health/ready`;
- `GET /mcp/tools/list`, autenticado pelo contexto assinado do gateway;
- `POST /mcp/tools/call`, em JSON-RPC 2.0 e com decisão de policy obrigatória.

Além do contexto assinado (HMAC), o runtime revalida o inner token trocado pelo
gateway: assinatura RS256 pela JWKS do Authorization Server, `iss`, `exp` e a
audiência ligada ao provedor (`aud == mcp:<provider>`), rejeitando também token de
outro tenant. Sem `MCP_INNER_TOKEN_ISSUER` e `MCP_INNER_TOKEN_JWKS_URL` (ou
`MCP_INNER_TOKEN_PUBLIC_KEY`) o `ready` e cada chamada falham fechado — o provedor
não executa ferramenta sem confirmar que a credencial foi emitida para ele.

Entrada e saída são validadas com JSON Schema 2020-12. Erros internos retornam erro
JSON-RPC genérico e ficam nos logs do provider; argumentos, resultados e paths sensíveis
não são incluídos na resposta de erro nem no evento local de auditoria.

## `contracts-mcp`

Provider somente leitura sobre `manifests/` e `contracts/tools/`:

| Tool | Scope | Efeito observável |
|---|---|---|
| `contracts_list` | `contracts:read` | Carrega e filtra os contratos canônicos atuais |
| `contracts_get` | `contracts:read` | Resolve um contrato por provider e nome |
| `contracts_validate_catalog` | `contracts:validate` | Executa as validações cruzadas de manifests, dependências e referências |

O repositório é montado como `/workspace:ro`; o serviço não escreve contratos nem
manifests.

## `artifact-provenance-mcp`

Provider somente leitura sobre arquivos regulares confinados ao worktree:

| Tool | Scope | Efeito observável |
|---|---|---|
| `provenance_hash_artifact` | `provenance:read` | Calcula SHA-256, tamanho e estado Git do arquivo observado |
| `provenance_verify_artifact` | `provenance:verify` | Compara o SHA-256 esperado com o conteúdo atual |
| `provenance_build_statement` | `provenance:read` | Produz statement em memória para até 100 artefatos |

Paths que escapam do worktree, `.git`, nomes típicos de credenciais e extensões de chave
são recusados. O limite padrão por arquivo é 100 MiB e pode ser reduzido com
`PROVENANCE_MAX_FILE_BYTES`. Os comandos Git usam argumentos explícitos, `shell=False`,
timeout e diretório de trabalho confinado.

## Auditoria de qualidade

`scripts/audit_mcp_tools.py` descobre implementações Python e TypeScript, inclusive
diretórios legados, `services/*` e scripts raiz. Ele compara:

```text
declared_tools
listed_tools
dispatchable_tools
catalog_tools
contract_tools
schema_tools
tested_tools
documented_tools
```

O relatório humano fica em `docs/reviews/mcp-tools-quality-baseline.md`; a evidência
estruturada fica em `generated/mcp-tools-audit.json`. O modo abaixo falha quando uma tool
de provider publicado no gateway não comprova schema de entrada/saída, contrato, testes,
documentação, autenticação, tenant, auditoria ou tratamento de erro:

```powershell
python scripts/audit_mcp_tools.py `
  --output docs/reviews/mcp-tools-quality-baseline.md `
  --json-output generated/mcp-tools-audit.json `
  --fail-on-runtime-gaps
```

Detecções de segredo, comando, chamada externa, destrutividade, placeholder e falso
sucesso são heurísticas conservadoras para revisão. O script não importa providers e,
portanto, não dispara startup, rede ou alteração de estado durante a auditoria.

## Fluxo de publicação

1. editar o manifest e os contratos canônicos;
2. executar `scripts/validate_mcp_manifests.py`;
3. regenerar as projeções com `scripts/generate_mcp_artifacts.py`;
4. executar testes do provider, gateway e control plane;
5. executar o auditor com `--fail-on-runtime-gaps`;
6. construir e executar smoke test do container com dependências reais.

O gate agregado para automação local ou `pipeline-mcp` é:

```powershell
python scripts/check_mcp_runtime_quality.py
```

GitHub Actions não faz parte desse fluxo. Os mesmos comandos são gates locais e podem ser
registrados por `pipeline-mcp`, que não executa CI/CD.
