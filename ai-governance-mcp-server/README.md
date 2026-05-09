# ai-governance-mcp-server

> MCP Server centralizado de governança para agentes de IA do ecossistema
> `dataforalltech`. Agentes consultam este servidor antes de implementar
> qualquer alteração — diretrizes, políticas, validação de decisão, checklist
> operacional e formato obrigatório de resposta vivem aqui.

> 📋 **Histórico de mudanças**: [CHANGELOG.md](CHANGELOG.md)
> 🏛️ **Decisões arquiteturais**: [docs/decisions/](docs/decisions/) (ADRs)
> 🛠️ **Runbook operacional**: [OPERATIONS.md](OPERATIONS.md) (deploy, troubleshoot, rollback)

## Objetivo

Termos múltiplos repositórios e múltiplos agentes em paralelo cria um
problema clássico: cada agente decide local, sem visão do conjunto. Este
MCP é a **fonte central de verdade** para:

1. Diretrizes universais (`AGENTS.md` de governança).
2. Regras por camada (frontend, backend, database, integrations,
   infrastructure, security, observability, testing).
3. Política de fallback.
4. Política de mudança de contrato.
5. Lista canônica de ações proibidas.
6. **Validação automatizada da decisão proposta** antes da implementação.
7. Checklist pré-execução e formato obrigatório de resposta final.
8. Busca textual na base de conhecimento.

O servidor **não** altera código, **não** acessa repositórios, **não**
roda em nome do agente. Ele só fornece informação operacional estruturada.

## Instalação

Pré-requisito: Python ≥ 3.11.

```bash
cd ai-governance-mcp-server
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Opcional — copiar `.env.example` para `.env` se quiser sobrescrever defaults:

```bash
cp .env.example .env
```

Variáveis disponíveis (todas opcionais):

| Variável | Default | Função |
|---|---|---|
| `GOVERNANCE_KB_PATH` | `./knowledge-base` | Pasta com os arquivos `.md` da base |
| `GOVERNANCE_LOG_LEVEL` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR` |
| `GOVERNANCE_LOG_FORMAT` | `json` | `json \| text` |
| `GOVERNANCE_SEARCH_DEFAULT_LIMIT` | `5` | Limite default de hits |
| `GOVERNANCE_SEARCH_MAX_LIMIT` | `20` | Teto de hits por chamada |
| `GOVERNANCE_SEARCH_SNIPPET_LENGTH` | `400` | Tamanho do trecho retornado |

## Execução local

```bash
# Via entry point (após pip install -e .)
ai-governance-mcp-server

# Ou pelo módulo
python -m src.server.mcp_server
```

O servidor fala MCP via **stdio** — você não verá saída útil no terminal
diretamente; ele é invocado por um cliente MCP (ex.: Claude Desktop, Cursor,
seus próprios agentes via SDK).

Logs estruturados vão para **stderr** (nunca stdout — stdout é o canal MCP).

## Conectando agentes ao MCP

### Opção recomendada: Docker

Imagem oficial em `d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server`. Sem instalar Python no host. Para Claude Desktop ou Claude Code:

```json
{
  "mcpServers": {
    "ai-governance": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/abs/path/to/suggestions:/app/knowledge-base/suggestions",
        "d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0"
      ]
    }
  }
}
```

Volume mount em `/app/knowledge-base/suggestions` é obrigatório se você quer histórico persistente de sugestões. Detalhes completos (tags disponíveis, autenticação ACR, atualização, build local) em [OPERATIONS.md §6.2](OPERATIONS.md#62-distribuição-via-docker-recomendado).

### Claude Desktop

Edite `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
ou o equivalente:

```json
{
  "mcpServers": {
    "ai-governance": {
      "command": "ai-governance-mcp-server",
      "env": {
        "GOVERNANCE_KB_PATH": "/caminho/absoluto/para/knowledge-base"
      }
    }
  }
}
```

### Cursor

Em `Settings → MCP`:

```json
{
  "ai-governance": {
    "command": "python",
    "args": ["-m", "src.server.mcp_server"],
    "cwd": "/caminho/para/ai-governance-mcp-server"
  }
}
```

### Claude Agent SDK (Python)

```python
from anthropic import Anthropic
# carregue o MCP via configuração de mcp_servers do SDK do agente
```

Use a forma documentada pelo SDK; o servidor é stdio-based e segue o
protocolo MCP padrão.

## Tools disponíveis

### Governança e validação (textuais)

| Tool | Função |
|---|---|
| `get_agent_guidelines` | Diretrizes aplicáveis ao contexto (repo, task, layer) |
| `get_layer_policy` | Política de uma camada específica |
| `get_forbidden_actions` | Lista canônica de ações proibidas |
| `validate_agent_decision` | **Valida e bloqueia decisões perigosas** |
| `get_fallback_policy` | Quando fallback é permitido e suas condições |
| `get_contract_change_policy` | Regras + checklist para mudança de contrato |
| `get_final_response_template` | Template obrigatório de resposta final |
| `get_pre_execution_checklist` | Checklist a executar antes de implementar |
| `search_governance_knowledge` | Busca textual na knowledge-base |

### Grafo do ecossistema (estruturais)

Seedado a partir de `knowledge-base/ecosystem.yaml` — modela repositórios, serviços, libs privadas, contratos, portas e times com arestas tipadas (`uses_lib`, `provides_api`, `consumes`, `produces_event`, `deprecated_by`, `replaces`, `runs_on_port`, `based_on`, `owns`).

| Tool | Função |
|---|---|
| `query_ecosystem_graph` | Lista nós (filtra por `kind`/`status`), ou vizinhos diretos com filtro de `relation`/`direction`. Use `query='stats'` para métricas. |
| `find_consumers_of` | Quem consome o que o nó produz/provê. Resolve via contratos (provides_api/produces_event → consumes/consumes_event) e via uses_lib para libraries. |
| `find_dependencies_of` | O que o nó depende. `max_depth` 1–5 para BFS limitada. |
| `get_service_metadata` | Atributos completos + dependências diretas + consumidores + `canonical_redirect` quando o nó está deprecado (aponta para o substituto). |

### Sugestões cross-repo (canal entre agentes)

Quando um agente trabalhando no repo A percebe algo que melhoraria no repo B, ele registra uma sugestão via MCP. Outros agentes (e humanos) listam, triam e atualizam status. Persistência: 1 arquivo JSON por sugestão em `<kb>/suggestions/<id>.json` (audit trail por padrão, git-trackeável).

| Tool | Função |
|---|---|
| `submit_suggestion` | Cria sugestão para outro repo. `target_repo` aceita id canônico ou alias; deprecated_by é seguido automaticamente para o substituto (gravado em `target_repo_canonical`). |
| `list_suggestions` | Filtra por target_repo, status, category, severity, source_agent. Default: 20 mais recentes. Resolução de alias no filtro também funciona. |
| `get_suggestion` | Payload completo pelo id. |
| `update_suggestion_status` | Muda status (pending → acknowledged → accepted/rejected/done/duplicate). Histórico append-only com (ts, status, note, by). |

Categorias: `bug | improvement | refactor | security | performance | docs | test | contract | observability`. Severidades: `low | medium | high | critical`.

### Ownership, escopo e libs privadas

Cobrem perguntas de "onde implementar" e bloqueios canônicos da AGENTS.md (§18 libs privadas, §47 portas, §49 responsabilidades).

| Tool | Função |
|---|---|
| `get_service_ownership` | O que o serviço possui, o que NÃO deve fazer (`explicit_non_responsibilities`), e quem ele chama. Usar antes de começar a tarefa para confirmar que está no serviço certo. |
| `get_service_dependencies` | Upstream + downstream do serviço para análise de impacto. Use ANTES de `validate_agent_decision(changes_contracts=True)`. |
| `get_port_map` | Mapa canônico porta → serviço, com próxima porta livre no range reservado 8022-8029. |
| `check_scope` | Detecta drift de escopo (volume excessivo, infra central, libs privadas, múltiplos serviços, arquivos suspeitos). |
| `validate_lib_change` | **HARD STOP §18** para mudanças em `platform-*-lib` / `platform-db-vector`. Devolve template de LIB CHANGE REQUEST pré-preenchido com consumidores. |

### Validação de migration + criação de ADR

| Tool | Função |
|---|---|
| `validate_migration` | Valida conteúdo de arquivo Alembic (sem ORM, `op.execute(sa.text(...))`, idempotência, sem DROP destrutivo na upgrade, downgrade obrigatório). |
| `create_adr` | Cria `docs/decisions/adr-NNNN.md` no repositório alvo com numeração automática. |

## Exemplos de chamadas

### Antes de iniciar uma tarefa

```json
{
  "tool": "get_pre_execution_checklist",
  "arguments": {
    "repository_name": "orders-service",
    "task_description": "Adicionar endpoint POST /orders/refund",
    "layer": "backend"
  }
}
```

### Validando uma decisão proposta

```json
{
  "tool": "validate_agent_decision",
  "arguments": {
    "repository_name": "payment-service",
    "task_description": "Tratar timeout do provider de cartão",
    "proposed_change": "try: provider.charge(amount)\nexcept Exception: pass",
    "affected_files": ["app/services/payment.py"],
    "affected_layers": ["backend", "integrations"],
    "changes_contracts": false,
    "adds_fallback": true
  }
}
```

Retorno (resumido):

```json
{
  "approved": false,
  "risk_level": "critical",
  "violations": [
    "Fallback silencioso detectado (try/except retornando estado fake ou pass).",
    "adds_fallback=True mas a descrição não menciona log/métrica/alerta."
  ],
  "required_actions": [
    "Remover o fallback silencioso. Propagar a exceção com contexto, ...",
    "Adicionar log.warning('fallback_triggered', ...) e métrica + alerta."
  ]
}
```

### Antes de mudar contrato

```json
{
  "tool": "get_contract_change_policy",
  "arguments": {
    "provider_service": "orders-service",
    "consumer_services": ["frontend-app", "billing-service"],
    "contract_type": "api",
    "proposed_change": "remover campo customer_email do payload de POST /orders"
  }
}
```

### Buscando regras

```json
{
  "tool": "search_governance_knowledge",
  "arguments": {
    "query": "fallback observável métrica",
    "limit": 3
  }
}
```

### Consultando o grafo do ecossistema

Quem consome um serviço:

```json
{
  "tool": "find_consumers_of",
  "arguments": { "node_id": "rag-service" }
}
```

Verificar redirecionamento canônico de um repo deprecado:

```json
{
  "tool": "get_service_metadata",
  "arguments": { "node_id": "connectors-platform" }
}
```

Retorno (resumido):

```json
{
  "found": true,
  "canonical_redirect": "platform-connectors",
  "notes": ["⚠ Este nó está deprecado. Use 'platform-connectors' (canônico)."]
}
```

Listar todos os serviços ativos:

```json
{
  "tool": "query_ecosystem_graph",
  "arguments": { "kind": "service", "status": "active" }
}
```

### Sugerindo melhoria para outro repo

Agente trabalhando em `ai-governance-mcp-server` percebe uma falha de timeout no `platform-cdc`:

```json
{
  "tool": "submit_suggestion",
  "arguments": {
    "source_agent": "claude-code:caiog",
    "source_repo": "ai-governance-mcp-server",
    "target_repo": "platform-cdc",
    "category": "security",
    "severity": "high",
    "title": "Adicionar timeout no provider externo",
    "description": "A chamada em app/services/source.py não tem timeout configurado. Em caso de provider lento, o request fica pendurado indefinidamente.",
    "related_files": ["app/services/source.py"],
    "references": ["docs/runbooks/provider-timeout.md"]
  }
}
```

Triagem por humano/outro agente:

```json
{ "tool": "list_suggestions", "arguments": { "target_repo": "platform-cdc", "status": "pending" } }

{ "tool": "update_suggestion_status",
  "arguments": {
    "suggestion_id": "20260505T221501123456-a1b2c3d4",
    "new_status": "accepted",
    "note": "Vai virar PR na próxima sprint",
    "by": "caiog"
  }
}
```

Dependências transitivas (BFS limitada):

```json
{
  "tool": "find_dependencies_of",
  "arguments": { "node_id": "agents-factory", "max_depth": 2 }
}
```

## Comportamento esperado do agente que consome este MCP

1. Ao receber a tarefa, chamar `get_pre_execution_checklist`.
2. Identificar a(s) camada(s) afetada(s) e chamar `get_layer_policy` para cada.
3. Antes de fazer commit/aplicar, chamar `validate_agent_decision`.
4. Se `approved=false`, **refazer a proposta** — não ignorar.
5. Responder no formato de `get_final_response_template`.

## Adicionando novas políticas

1. **Política em texto**: criar/editar arquivo em `knowledge-base/<nome>.md`.
   - Sempre incluir seções `## Pode`, `## Não pode`, `## Errado`, `## Correto`.
   - O servidor recarrega ao reiniciar.

2. **Nova regra de validação automatizada** (`validate_agent_decision`):
   - Adicionar pattern regex em `src/tools/decision_tool.py`.
   - Adicionar teste em `tests/test_decision_validator.py` cobrindo o caso.
   - Caso CRITICAL → setar `approved=False`. Caso HIGH → marcar risco.

3. **Nova tool MCP**:
   - Criar função pura em `src/tools/<tema>_tool.py`.
   - Exportar em `src/tools/__init__.py`.
   - Registrar schema + dispatch em `src/server/mcp_server.py`.
   - Escrever teste em `tests/`.

4. **Atualizar o grafo do ecossistema**:
   - Editar `knowledge-base/ecosystem.yaml`.
   - Tipos válidos: `repository | service | library | contract | team | port`.
   - Relações válidas: `depends_on | consumes | produces | owns | deprecated_by | replaces | runs_on_port | uses_lib | provides_api | consumes_event | produces_event | based_on`.
   - Reiniciar o servidor; o `EcosystemGraph` valida no boot e reporta nós órfãos / kinds desconhecidos / arestas quebradas.
   - Os testes em `tests/test_graph.py` consultam o YAML real — se você modela algo novo crítico do ecossistema (ex.: serviço novo, novo contrato), adicione um caso lá.

## PR validation (`.github/workflows/pr-validate.yml` + `scripts/pr_validate.py`)

GitHub Action que invoca `validate_agent_decision` no diff do PR e posta o resultado como comentário. Por default `continue-on-error: true` — informativo, não bloqueia merge enquanto o validator está em fase de calibração.

```bash
# Local: dry-run contra branch
python scripts/pr_validate.py --base main --head HEAD --dry-run

# Local: salvar comentário em arquivo (sem postar)
python scripts/pr_validate.py --base origin/main --output-comment /tmp/comment.md

# CI (GitHub Actions): variáveis GITHUB_BASE_REF/GITHUB_HEAD_REF/PR_NUMBER já automaticas
python scripts/pr_validate.py --post-comment
```

Comentário renderiza com emoji indicador (🛑 BLOCKED, ⚠️ HIGH RISK / Medium, ✅ OK), violations, required actions, recommendations e notes. Truncamento, fail-safe e exit codes idênticos ao hook de pre-commit.

## Pre-commit hook (`scripts/precommit_validate.py`)

Hook git que invoca `validate_agent_decision` automaticamente no diff staged. Bloqueia o commit se a validação reprovar com `risk=critical` (silent fallback, hardcoded credential, auth bypass, mock em prod, deleção de teste, DROP destrutivo). Avisa em `high`/`medium` sem bloquear (configurável).

### Instalação

Em **qualquer repositório do ecossistema** (não precisa ser este projeto):

```bash
# 1. Garanta que o ai-governance-mcp-server está no PATH ou via Python direto.
pip install -e /caminho/para/ai-governance-mcp-server

# 2. Crie o hook git no repo onde você commita:
cat > .git/hooks/pre-commit <<'EOF'
#!/usr/bin/env bash
exec python /caminho/para/ai-governance-mcp-server/scripts/precommit_validate.py
EOF
chmod +x .git/hooks/pre-commit
```

Ou via `pre-commit` framework, em `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: ai-governance-validate
        name: AI Governance pre-commit validate
        entry: python /caminho/para/ai-governance-mcp-server/scripts/precommit_validate.py
        language: system
        always_run: true
        stages: [pre-commit]
```

### Variáveis de ambiente

| Variável | Default | Função |
|---|---|---|
| `PRECOMMIT_REPO_NAME` | basename do `git rev-parse --show-toplevel` | Nome canônico do repo a passar para o validator |
| `PRECOMMIT_TASK_DESCRIPTION` | subject de `HEAD` + contagem de arquivos | Descrição da tarefa |
| `PRECOMMIT_BLOCK_ON_HIGH` | `0` | `1` para bloquear também em risk=high |

### Exit codes

- `0` — OK ou WARN; commit prossegue.
- `1` — BLOCK; commit é abortado.

### Comportamento defensivo

- Não roda em merge/rebase/amend.
- Falha silenciosa (warning + exit 0) se MCP server não puder ser spawned — hook nunca quebra commit por causa de problema de transporte.
- Truncamento do diff em 8000 chars (limite do `description` do validator).
- Skip se há mais de 50 arquivos staged (sugere splitar o commit).

### Modo dry-run

```bash
python scripts/precommit_validate.py --dry-run
```

Mostra o payload que seria enviado, sem invocar o MCP.

## Scanner de drift (`scripts/scan_ecosystem.py`)

Detecta divergência entre o `ecosystem.yaml` e os repositórios reais no disco. Roda em segundos e expõe drift acumulado:

- **Conflitos** (porta diferente entre YAML e `.env`/docker-compose).
- **Faltam no YAML**: repos que existem no disco mas não estão modelados.
- **Faltam no disco**: serviços ativos no YAML sem repo correspondente.
- **Lib drift**: dependências `platform-*-lib` em `pyproject.toml` que diferem das edges `uses_lib`.
- **Consume drift**: `URL_*` em `.env` apontando para serviços não modelados como `consumes`.

```bash
# Auto-detect (sobe na árvore até achar diretório com >=2 repos)
python scripts/scan_ecosystem.py

# Path explícito
python scripts/scan_ecosystem.py --path ~/Documents/repositorios

# Output JSON para pipelines
python scripts/scan_ecosystem.py --format json --output drift.json
```

**Exit codes**: `0` se zero conflitos (warnings ok), `1` se há conflito de porta ou lib drift, `2` se input inválido.

O scanner **não modifica** o YAML. Drift é input para revisão humana — você decide caso a caso se o YAML está desatualizado, se o repo está com config errado, ou se houve renomeação não-canônica.

## Testes

```bash
pytest                    # roda toda a suíte
pytest tests/test_decision_validator.py -v
```

Os testes usam a knowledge-base real do repositório — qualquer drift entre
código e base aparece como falha.

## Evoluindo para RAG / vector search

A camada `GovernanceRepository.search` é a única que conhece a estratégia
de busca atual (heurística por frequência + bonus de heading). Para evoluir:

1. Indexar `knowledge-base/` em um vector store (Qdrant, pgvector, etc.).
2. Implementar `GovernanceRepository.search` para consultar embeddings.
3. As tools (`search_governance_knowledge`, etc.) **não mudam**.

A interface de retorno (`{source, section, snippet, score}`) já é
compatível com retrievers vetoriais.

## Não-objetivos

- **Não** edita código de outros repositórios.
- **Não** roda comandos no terminal do agente.
- **Não** depende de serviço externo obrigatório.
- **Não** armazena credencial.
- **Não** substitui revisão humana — é a primeira camada, não a única.
