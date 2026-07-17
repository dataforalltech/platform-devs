# Formato obrigatório de resposta final do agente

Toda tarefa de implementação termina com uma resposta nesse formato. A tool
`get_final_response_template` devolve este template de forma estruturada
(JSON + markdown).

## Template

```markdown
## Resposta final do agente

### O que foi alterado
- ...  (bullets curtos; sem "vários ajustes")

### Por que foi alterado
- ...  (motivação: bug, requisito, ADR, ticket; cite a fonte)

### Arquivos modificados
- `path/to/file.py` — o que mudou nele
- `path/to/other.ts` — o que mudou nele

### Riscos
- ...  (regressão potencial, breaking change, performance, segurança)
- "Nenhum identificado" é resposta válida — só se for verdade.

### Testes executados
- `pytest tests/unit` — passed (102 passed, 0 failed)
- `pytest tests/integration` — passed
- `npm run typecheck` — passed
- `npm run lint` — passed

### Testes não executados e motivo
- E2E completo: ambiente de homologação indisponível, registrado para próximo passo.
- "Nenhum" é resposta válida — só se for verdade.

### Impacto em outros serviços
- `service-x` consome a API alterada — atualizar antes do merge.
- "Nenhum" é resposta válida — só se a mudança for puramente interna.

### Pendências
- Comunicar time Y sobre breaking change.
- ADR pendente em docs/decisions/.
- "Nenhuma" é resposta válida — só se for verdade.
```

## Variantes por tipo de tarefa

### Bugfix — adicionar:

```markdown
### Teste de regressão
- `tests/regression/test_bug_1234.py::test_calc_with_zero_items` — falharia antes do fix; passa agora.
```

### Migration — adicionar:

```markdown
### Plano de rollback
- `alembic downgrade -1` reverte a migration.
- Caso o backfill precise ser revertido: ...
```

### Refactor — adicionar:

```markdown
### Comportamento inalterado
- Mesma suíte de testes passa antes e depois.
- Sem mudança em endpoints, eventos ou schemas.
```

## Por que esse formato

Cada seção responde a uma pergunta operacional crítica:

| Seção | Pergunta |
|---|---|
| O que foi alterado | "O que muda no produto?" |
| Por que | "Como rastreio essa decisão?" |
| Arquivos | "O que reviso?" |
| Riscos | "O que pode dar errado?" |
| Testes executados | "Tenho confiança no que rodei?" |
| Testes não executados | "O que ficou de fora? por quê?" |
| Impacto | "Quem mais é afetado?" |
| Pendências | "O que ainda precisa acontecer?" |

Resposta sem essas seções é incompleta — o reviewer humano não consegue agir sobre ela.
