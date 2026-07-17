# AGENTS.md — Política universal para agentes de IA

> Documento canônico exposto pelo MCP `ai-governance-mcp-server`.
> Este arquivo é a **política mínima universal**. Cada repositório do
> ecossistema pode ter seu próprio AGENTS.md local com regras adicionais —
> mas nenhum pode contradizer este.

## 1. Princípios

1. **Entender antes de alterar.** Leia README, AGENTS.md local e ADRs. Tarefa ambígua → pergunte ao humano.
2. **Não saia do escopo.** PR pequeno, focado, reversível.
3. **Não modifique contratos sem coordenação.** API, eventos, schemas, interfaces de libs públicas.
4. **Decisões arquiteturais grandes exigem ADR.** Substituir biblioteca, mudar padrão de cache, novo protocolo.
5. **Respeite os padrões do repo.** Estilo, libs, naming. Padrão local sempre vence preferência do agente.
6. **Falha visível é melhor que sucesso falso.** Logue, alerte, propague — nunca esconda.

## 2. Proibições explícitas

| # | Proibição | Por quê |
|---|-----------|---------|
| 1 | Fallback silencioso | Esconde falha real; mascara incidentes |
| 2 | Hardcoded de credenciais, URLs, IDs, tokens | Quebra reproduzibilidade; expõe segredo |
| 3 | Resolver bug de backend no frontend (ou vice-versa) | Solução na camada errada |
| 4 | `try/except` genérico engolindo erro | Bloqueia observabilidade |
| 5 | Mock em código produtivo | Mascara problemas reais |
| 6 | Alterar contrato sem atualizar consumidores | Quebra produção |
| 7 | Apagar/skipar testes para fazer build passar | Esconde regressão |
| 8 | Bypass de auth/autz | Cria vulnerabilidade real |
| 9 | Abstração prematura sem ≥3 usos reais | Dívida técnica imediata |
| 10 | Pular hooks/CI (`--no-verify`) | Hooks existem por motivo |
| 11 | Nova dependência sem justificativa | Aumenta supply chain risk |
| 12 | Refactor amplo fora do escopo | Polui diff; dificulta revisão |
| 13 | Reduzir validação/observabilidade para resolver bug | Cria cegueira operacional |
| 14 | Mudar `.gitignore`/config compartilhada sem necessidade | Afeta todo o time |

> **Regra de ouro**: se você está prestes a fazer algo desta lista, **pare** e
> pergunte ao humano. Sempre há alternativa correta.

## 3. Como o agente deve atuar

1. Ler AGENTS.md local + README + ADRs.
2. Chamar `get_pre_execution_checklist` deste MCP com a tarefa.
3. Implementar a alteração mínima necessária.
4. Chamar `validate_agent_decision` com a proposta antes de finalizar.
5. Resolver violações reportadas (não ignorar).
6. Responder no formato de `get_final_response_template`.

## 4. Falha visível

Quando algo falha em integração, o caminho correto é:

```python
# CORRETO
try:
    result = provider.charge(amount)
except ProviderTimeout:
    log.exception("provider_timeout", extra={"provider": "x", "amount": amount})
    metrics.inc("provider.timeout")
    raise
```

```python
# ERRADO — fallback silencioso
try:
    return provider.charge(amount)
except Exception:
    return {"status": "ok"}  # mente para o caller
```

## 5. Hard stops

Pare e escale para humano quando:

- A tarefa exige bypass de auth.
- A tarefa exige `DROP`/`TRUNCATE` em produção.
- A tarefa exige alterar contrato cujo consumidor é desconhecido.
- O teste relevante está quebrado e a "solução fácil" é apagá-lo.
- Você não tem certeza do que a tarefa pede.

## Referências cruzadas

- `forbidden-actions.md` — lista detalhada com motivo + alternativa
- `fallback.md` — quando fallback é permitido
- `contracts.md` — regras de mudança de contrato
- `final-response-format.md` — template obrigatório de resposta
