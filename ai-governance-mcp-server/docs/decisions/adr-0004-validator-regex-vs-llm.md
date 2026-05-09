# ADR 0004 — Validator: heurística regex em vez de LLM-as-judge

**Data**: 2026-05-05
**Status**: Aceito (com plano de evolução)
**Decisor**: @caiog (review humano)
**Implementação**: commit `19b2a44`

## Contexto

`validate_agent_decision` precisa decidir se uma proposta de mudança viola política (fallback silencioso, hardcoded de credencial, bypass de auth, mock em prod, alteração de contrato sem consumidores, scope drift, etc.). É chamada toda vez que um agente está prestes a aplicar mudança.

Opções:

1. **Regex sobre o `proposed_change` text + flags booleanos explícitos.**
2. LLM-as-judge (Anthropic API com prompt contendo as políticas).
3. Híbrido: regex para casos óbvios + LLM para ambíguos.
4. Análise estática (AST) para detectar padrões específicos no código.

## Decisão

**Opção 1**: regex + flags booleanos. **Plano de evolução para opção 3** quando os falsos positivos acumularem.

## Consequências

### Positivas

- **Determinístico** — testável em pytest, reproduzível, sem custo por chamada.
- **Sem dependência externa** — alinhado com briefing original ("não use credenciais reais", "não use serviços externos obrigatórios").
- **Latência <10ms** — sem round-trip a LLM.
- **Bloqueia casos clássicos** — silent fallback patterns (`try/except: pass`, `return -1`), `sk-` prefixed tokens, `MockProvider`, `DROP TABLE` em código de app, deleção de teste, bypass de auth (`X-Skip-Auth`, `disable_authentication`).
- **Negation-aware** — depois do bug `"Não removi teste"` reportado pelo dogfood, adicionamos `_is_negated()` que olha 40 chars antes de cada match e ignora se houver negação (PT/EN: não, sem, never, nunca, jamais, no, not, don't, didn't).

### Negativas

- **Falso positivo em strings literais** — regex `_DEPENDENCY_PATTERNS` casa `pyproject.toml` em qualquer texto, incluindo docstrings e comentários. Precisa refinar para distinguir "menção" de "modificação real".
- **Não pega mudanças sutis** — refactor que ESCONDE a lógica em uma camada acima do regex passa batido. Ex.: criar `def fake_charge(): return {"status": "ok"}` e chamar isso em vez do real — sem padrão `try/except` óbvio, regex não pega.
- **Calibração manual** — adicionar uma regra nova exige editar `decision_tool.py`, escrever pattern, testar.
- **Não entende contexto cross-arquivo** — regex roda só no `proposed_change` que veio na chamada. Não consegue ver "este arquivo já tinha um fallback parecido".

## Alternativa rejeitada (por enquanto)

### LLM-as-judge

- Cobriria casos sutis e contextuais.
- Mas:
  - **Latência** — 2–10s por chamada faria pre-commit hook impraticável.
  - **Custo** — múltiplas chamadas por dia para cada agente do ecossistema.
  - **Não-determinístico** — flaky em CI.
  - **Vendor lock-in** — dependência de Anthropic API ou similar.
  - **Não substitui regex** — para os casos óbvios (DROP, hardcoded sk-key), regex é mais rápido E confiável.

## Plano de evolução: híbrido

Quando os falsos positivos atingirem volume incômodo (~5+ por semana), adicionar uma fase 2:

1. Manter regex como **filtro de primeira linha** — bloqueio imediato em padrões conhecidos perigosos (silent fallback, `DROP`, etc.).
2. Adicionar LLM-as-judge **apenas para casos não-óbvios** — quando o regex marcar `risk=high` por palavra-chave que pode ser falso positivo, escalar pra um modelo barato (Haiku) com a política como contexto + a proposta + o veredicto regex. Modelo confirma ou desclassifica.
3. Cache do veredicto LLM por hash do `proposed_change` para evitar re-cobrar a mesma análise.
4. Métricas: % de chamadas que escalam, custo médio por chamada, tempo médio.

## Refinamentos pendentes para regex (curto prazo)

Sem tirar regex da fase 1, dá para reduzir falsos positivos:

1. **Escopo de detecção**: olhar só linhas `+` (adicionadas) do diff, não o blob inteiro. Já adotado em `scripts/precommit_validate.py` parcialmente; estender para `decision_tool.py`.
2. **Lookahead específico para deps**: `_DEPENDENCY_PATTERNS` deveria casar `pyproject.toml` apenas em contexto de `+` lines OR com `requires`/`dependencies` próximo.
3. **Whitelist de extensões textuais** (`.md`, docstrings) — palavras-chave em texto técnico não-código não deveriam disparar regras de código.

Estes refinamentos são candidatos ao próximo commit de manutenção do validator.

## Referências

- [src/tools/decision_tool.py](../../src/tools/decision_tool.py)
- [tests/test_decision_validator.py](../../tests/test_decision_validator.py)
- AGENTS.md §2 (proibições explícitas) e §15 (HARD STOPS)
