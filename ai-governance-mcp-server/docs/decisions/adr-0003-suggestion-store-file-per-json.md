# ADR 0003 — Sugestões cross-repo: file-per-suggestion JSON

**Data**: 2026-05-05
**Status**: Aceito
**Decisor**: @caiog (review humano)
**Implementação**: commit `e0420e6`

## Contexto

Agentes precisam de um canal para registrar "enquanto eu trabalhava no repo A, percebi que o repo B precisa disso". Outros agentes (e humanos) listam, triam, atualizam status. Não é um issue tracker — é mais leve, persistente entre sessões, auditável.

Opções de persistência:

1. **1 arquivo JSON por sugestão em `<kb>/suggestions/<id>.json`.**
2. SQLite local (`<kb>/suggestions.db`).
3. JSONL append-only (`<kb>/suggestions.jsonl`).
4. Issues do GitHub via API.
5. Banco compartilhado (Postgres).

## Decisão

**Opção 1**: file-per-suggestion JSON. ID é `YYYYMMDDTHHMMSSffffff-XXXXXXXX` (ordenável + colisão-resistente).

## Consequências

### Positivas

- **Audit trail nativo via git** — cada sugestão é um arquivo. `git log knowledge-base/suggestions/` mostra histórico completo. Diff de status é diff de arquivo.
- **Concorrência trivial** — uma chamada MCP é atômica em termos de filesystem, e cada sugestão tem nome único. Sem race conditions.
- **Diff humano fácil** — operações team pode revisar sugestões em PR como qualquer outro arquivo. Markdown da `description` renderiza no GitHub.
- **Sem schema migration** — adicionar campo é editar Pydantic + arquivos antigos continuam válidos (Pydantic permite extras como ignorados/avisados).
- **Backup é `cp -r`** — sem dump/restore.
- **Listagem ordenada por ID lexicográfico** — `sorted(glob('*.json'), reverse=True)` devolve mais novos primeiro sem indexação.

### Negativas

- **Não escala para milhões de sugestões** — directory listing fica lento com >10k arquivos em alguns filesystems. Para o uso esperado (dezenas/centenas por mês), zero problema.
- **Filtros são lineares** — `list_suggestions` lê todos os arquivos. Para volume grande, virar índice em memória ou trocar para SQLite. Aceitável até ~5k sugestões.
- **Sem transações multi-arquivo** — não conseguimos atualizar 2 sugestões atomicamente. O modelo append-only por arquivo evita esse cenário (cada operação muta 1 arquivo).
- **Ordenação dependente do clock** — IDs são sortable porque embedam timestamp. Se o relógio voltar (NTP correction, suspend/resume), pode haver IDs fora de ordem. Mitigação: microssegundos no timestamp + suffix UUID.

## Alternativas rejeitadas

### SQLite

- Mais "produtivo" para queries ricas, mas cria barreira pra revisão humana via PR (binário).
- Ganho de filtros em escala atual é zero.

### JSONL append-only

- Mais compacto (1 arquivo). Mas:
- Atualizar status exige reescrever o arquivo inteiro ou anexar evento e folding na leitura — complica significativamente sem ganho operacional.
- Ler 1 sugestão por id requer scan linear (mais lento que abrir 1 arquivo direto).

### GitHub Issues

- Auditável, com UI, integrado.
- Mas: depende de rede, requer credencial, ata de proteção contra spam, vincula governança a um vendor.
- Vale revisitar quando: as sugestões realmente virarem trabalho rastreado de produto.

### Postgres compartilhado

- Resolveria multi-tenancy se múltiplos servidores MCP compartilhassem sugestões. Hoje isso não é caso de uso.
- Adiciona dep de infra. Migra-se quando necessário.

## Migração futura

Se virarmos para SQLite ou Postgres:

1. A interface pública do `SuggestionStore` (4 métodos: `create`, `get`, `list`, `update_status`, `stats`) é estável.
2. Reescrever a implementação dos 4 métodos.
3. Manter o id externo (`YYYYMMDDTHHMMSSffffff-XXXXXXXX`) como chave primária para preservar referências externas (PR/issue links).
4. Migration do filesystem: ler todos os arquivos, fazer bulk insert no novo backend, parar de gravar no filesystem.

## Referências

- [src/knowledge/suggestion_store.py](../../src/knowledge/suggestion_store.py)
- [src/models/suggestion.py](../../src/models/suggestion.py)
- [src/tools/suggestion_tool.py](../../src/tools/suggestion_tool.py)
