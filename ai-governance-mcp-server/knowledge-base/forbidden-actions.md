# Ações proibidas — lista canônica

Esta é a lista canônica de ações proibidas. A tool `get_forbidden_actions`
expõe a mesma lista de forma estruturada.

| ID | Ação | Motivo | Alternativa correta |
|---|---|---|---|
| `silent-fallback` | Fallback silencioso (try/except retornando estado falso ou pass) | Esconde a falha real, mascara incidentes em produção | Propagar a exceção com `log.exception(...)`, métrica e tratamento explícito |
| `hardcoded-config` | Hardcoded de URL, credencial, token, ID de tenant ou data | Quebra reproduzibilidade, expõe segredo, impede multi-ambiente | Vir de configuração tipada (env/cofre) |
| `cross-layer-shortcut` | Resolver bug de backend no frontend (ou vice-versa) | Solução na camada errada, mascara dívida técnica | Corrigir na camada responsável |
| `generic-try-except` | `try/except Exception: pass` em integração | Engole erro, bloqueia observabilidade | Capturar exceção específica + log + métrica |
| `mock-in-prod` | `MockProvider`/fake retornando dado em código produtivo | Mascara problemas reais, divergência prod/teste | Failover documentado com flag + alerta |
| `contract-break` | Alterar contrato sem atualizar consumidores e testes | Quebra cadeia em runtime | Versionar + comunicar + manter compat durante deprecation |
| `delete-tests` | Apagar/skip permanente de teste para passar build | Esconde regressão | Investigar e corrigir; se teste estava errado, PR explicando |
| `auth-bypass` | Bypass de autenticação/autorização | Cria vulnerabilidade real e duradoura | Resolver propriamente; rota pública exige ADR |
| `premature-abstraction` | Criar factory/interface para "deixar genérico" | Dívida imediata | Aceitar repetição até existir caso real |
| `skip-hooks` | Pular hooks com `--no-verify`, `--skip-tests` | Hooks existem por motivo | Investigar o motivo do hook falhar |
| `weakened-validation` | Reduzir validação/segurança para passar build | Cria vulnerabilidade ou dado inválido em prod | Corrigir a causa do input inválido na origem |
| `broad-refactor` | Refactor amplo fora do escopo da tarefa | Polui diff, dificulta revisão e bissecção | PR dedicado de refactor |
| `unjustified-dependency` | Nova dependência sem justificativa | Aumenta supply chain risk | Avaliar alternativas, justificar no PR |
| `missing-observability` | Integração crítica sem log/métrica/alerta | Cria cegueira operacional | Log + métrica + alerta + runbook antes do merge |

## Sinais comuns na conversa

Se você se pegar dizendo (ou pensando):

- "É só temporário" → vira permanente em 100% dos casos.
- "Ninguém usa esse contrato" → quase sempre falso; você não procurou direito.
- "Vou aproveitar para refatorar" → escopo cresce, PR fica imbissecável.
- "É mais fácil esconder o erro" → fallback silencioso.
- "Esse hook tá quebrando, vou pular" → você está apagando uma proteção.
- "Vou só baixar essa lib aqui rápido" → supply chain risk.

…**pare** e reconsidere.
