# AGENTS.md — Política operacional para Agentes de IA

> Documento canônico e obrigatório para qualquer agente de IA (Claude Code, Cursor,
> Copilot, agentes internos via Claude Agent SDK ou outros frameworks) atuando em
> qualquer um dos ~35 repositórios do ecossistema `dataforalltech`.
>
> Este arquivo **substitui** o antigo `CLAUDE.md` deste template. Veja
> [CLAUDE.md](CLAUDE.md) — agora um ponteiro curto.
>
> **Aplicabilidade**:
> - **Parte I (§1–§15)** é universal — vale para todo o ecossistema, qualquer stack.
> - **Parte II (§16–§45)** é específica deste template Python/FastAPI e dos serviços
>   derivados dele. Outros repositórios (frontends, libs JS, ferramentas Go) seguem
>   apenas a Parte I, somada ao seu próprio AGENTS.md local.
>
> **Última revisão**: 2026-05-05.

---

## Sumário

### PARTE I — Política universal (todos os repositórios)

1. [Princípios gerais](#1-princípios-gerais)
2. [Proibições explícitas](#2-proibições-explícitas)
3. [Responsabilidade por camada](#3-responsabilidade-por-camada)
4. [Regras para fallback](#4-regras-para-fallback)
5. [Tomada de decisão](#5-tomada-de-decisão)
6. [Padrão de execução de tarefas](#6-padrão-de-execução-de-tarefas)
7. [Múltiplos agentes](#7-múltiplos-agentes)
8. [Contratos e APIs](#8-contratos-e-apis)
9. [Configuração e ambiente](#9-configuração-e-ambiente)
10. [Observabilidade](#10-observabilidade)
11. [Segurança](#11-segurança)
12. [Testes](#12-testes)
13. [Formato obrigatório de resposta](#13-formato-obrigatório-de-resposta)
14. [Checklist final obrigatório](#14-checklist-final-obrigatório)
15. [HARD STOPS — quando parar e escalar](#15-hard-stops--quando-parar-e-escalar)

### PARTE II — Padrões técnicos do template Python/FastAPI

16. [Sobre este template](#16-sobre-este-template)
17. [Mapa de bibliotecas privadas](#17-mapa-de-bibliotecas-privadas)
18. [Governance de bibliotecas privadas](#18-governance-de-bibliotecas-privadas)
19. [Estrutura de diretórios](#19-estrutura-de-diretórios)
20. [Service como Library](#20-service-como-library)
21. [Regras de import](#21-regras-de-import)
22. [Ordem de middlewares (LIFO)](#22-ordem-de-middlewares-lifo)
23. [Padrão de módulo (7 arquivos)](#23-padrão-de-módulo-7-arquivos)
24. [Documentação OpenAPI](#24-documentação-openapi)
25. [Padrão LogRepository](#25-padrão-logrepository)
26. [Operações de arquivo (`platform_files`)](#26-operações-de-arquivo)
27. [Convenções de nomenclatura no banco](#27-convenções-de-nomenclatura-no-banco)
28. [Convenções de queries SQL](#28-convenções-de-queries-sql)
29. [Convenções de migrations Alembic](#29-convenções-de-migrations-alembic)
30. [Criando um novo serviço](#30-criando-um-novo-serviço)
31. [Migrando um serviço existente](#31-migrando-um-serviço-existente)
32. [Template de `config.py`](#32-template-de-configpy)
33. [Checklist de validação](#33-checklist-de-validação)
34. [Requisitos de teste](#34-requisitos-de-teste)
35. [Auditoria de segurança](#35-auditoria-de-segurança)
36. [Convenções de eventos Kafka](#36-convenções-de-eventos-kafka)
37. [Padrão WebSocket](#37-padrão-websocket)
38. [Contrato de health check](#38-contrato-de-health-check)
39. [Anti-patterns](#39-anti-patterns)
40. [Migração Python 3.9 → 3.12](#40-migração-python-39--312)
41. [Checklist de novo módulo](#41-checklist-de-novo-módulo)
42. [Bloco de dependências para `requirements.txt`](#42-bloco-de-dependências-para-requirementstxt)
43. [Requisitos de CI/CD](#43-requisitos-de-cicd)
44. [Política de autenticação (sem rotas públicas)](#44-política-de-autenticação-sem-rotas-públicas)
45. [Endpoint interno de migração de tenant](#45-endpoint-interno-de-migração-de-tenant)
46. [Início rápido para agentes IA](#46-início-rápido-para-agentes-ia-quick-reference)
47. [Atribuições de portas — desenvolvimento local](#47-atribuições-de-portas--desenvolvimento-local)
48. [Perfis de ambiente — matriz de 5 perfis](#48-perfis-de-ambiente--matriz-de-5-perfis)
49. [Mapa de responsabilidades por serviço](#49-mapa-de-responsabilidades-por-serviço)
50. [Modelo operacional de agentes IA](#50-modelo-operacional-de-agentes-ia)
51. [Modo LAB — playground manual & de agentes IA](#51-modo-lab--playground-manual--de-agentes-ia)
52. [Prompt de agente Terraform / SRE](#52-prompt-de-agente-terraform--sre)
    - [52.1 CLIs, tooling e artefatos](#521--clis-tooling-e-artefatos)
    - [52.2 Backup de artefatos](#522--backup-de-artefatos)
    - [52.3 Integração com platform-connector](#523--integração-com-platform-connector)
    - [52.4 Entregáveis adicionais obrigatórios](#524--entregáveis-adicionais-obrigatórios)
    - [52.5 Ferramentas MCP aprovadas](#525--ferramentas-mcp-aprovadas-para-agentes-terraform--sre)
    - [52.6 Sandbox de dev cloud individual](#526--sandbox-de-dev-cloud-individual)
53. [Trinity Pattern — API + Lib + MCP Architecture](#53-trinity-pattern--api--lib--mcp-architecture)
    - [53.1 O que é Trinity?](#531--o-que-é-trinity)
    - [53.2 Aplicabilidade](#532--aplicabilidade)
    - [53.3 Estrutura obrigatória](#533--estrutura-obrigatória)
    - [53.4 Como o MCP se comunica com a API](#534--como-o-mcp-se-comunica-com-a-api)
54. [MCP Standards — Nomenclatura, Implementação, Governance](#54-mcp-standards--nomenclatura-implementação-governance)
    - [54.1 Tool Naming Convention](#541--tool-naming-convention)
    - [54.2 Tool Definition](#542--tool-definition)
    - [54.3 Response Format](#543--response-format)
    - [54.4 API Client & Configuration](#544--api-client--configuration)
    - [54.5 MCP Server Structure](#545--mcp-server-structure)
    - [54.6 Tool Implementation](#546--tool-implementation)
    - [54.7 Governance Rules](#547--governance-rules-must)
    - [54.8 Testing & CI/CD](#548--testing--cicd)
    - [54.9 Pre-deploy Checklist](#549--pre-deploy-checklist)

---

# PARTE I — Política universal

Esta parte aplica-se a **qualquer** agente de IA atuando em **qualquer** repositório
do ecossistema `dataforalltech`, independentemente de stack, linguagem ou domínio.
Backends Python, frontends Next.js, libs JS, ferramentas Go, scripts de infraestrutura —
todos seguem a Parte I.

---

## §0. ENFORCEMENT — session-mcp e ToolSearch obrigatórios

### Regra 1: Todo trabalho deve ser registrado no banco via session-mcp

**Inegociável.** Antes de qualquer tarefa, análise ou geração de código:

1. Chame `mcp__session-mcp__list_sessions(status="active", repo=<repo_atual>)`
   - Se houver: use o `session_id` existente
   - Se não houver: `mcp__session-mcp__start_session(title=<título>, objective=<objetivo>, repo=<repo>)`

2. Para cada entrega ou sub-tarefa, registre no banco:
   ```
   mcp__session-mcp__create_task(session_id, title, description)
   mcp__session-mcp__start_task(session_id, task_id)
   mcp__session-mcp__complete_task(session_id, task_id, result, commit_sha)
   ```

3. Ao concluir etapas significativas:
   ```
   mcp__session-mcp__save_checkpoint(session_id, summary)
   mcp__session-mcp__add_artifact(session_id, type, content)
   ```

4. Ao finalizar todo o trabalho:
   ```
   mcp__session-mcp__end_session(session_id, actor={type:"agent",id:"<NomeZilla>"}, rationale, final_summary)
   ```

**Impacto**: Sem registro, o trabalho é invisível ao sistema, não tem rastreabilidade, não pode ser auditado e quebrará compliance.

### Regra 2: Carregue schemas antes de invocar qualquer ferramenta MCP

**Obrigatório.** NUNCA invoque uma ferramenta MCP sem primeiro carregar seu schema:

```
ToolSearch("select:mcp__<servidor>__<tool1>,mcp__<servidor>__<tool2>")
```

Exemplos:
- `ToolSearch("select:mcp__session-mcp__start_session,mcp__session-mcp__create_task")`
- `ToolSearch("select:mcp__deploy-mcp__create_pr,mcp__deploy-mcp__merge_branch")`

**Por quê**: Schemas mudam entre versões. Presunção de parâmetros causa `InputValidationError`. Sempre carregue o schema atual antes de montar a chamada.

### Onde aplica

- **Todos os Zillas** (QAZilla, SecZilla, ArchZilla, BackZilla, FrontZilla, OpsZilla, POZilla, ProductZilla)
- **Todos os agentes Claude Code** neste ecossistema
- **Todos os MCPs** que invocam outros MCPs

---

## 1. Princípios gerais

Estes são os 6 princípios que orientam toda atuação. Tudo neste documento é uma
consequência operacional deles.

1. **Entenda o contexto antes de alterar qualquer código.**
   Leia o `README.md`, o `AGENTS.md` local, os `ADR`s relevantes e o código
   diretamente afetado. Se a tarefa é ambígua, pergunte ao humano antes de
   implementar.

2. **Não altere arquivos fora do escopo da tarefa.**
   Se a tarefa é "corrigir bug em `OrderService.calcular`", não refatore o
   `PaymentService` "de quebra". Cada PR deve ser focado e rastreável.

3. **Não modifique contratos sem justificativa explícita e coordenação.**
   Schemas de API, payloads de eventos Kafka, formatos de WebSocket, interfaces
   de funções públicas em libs compartilhadas — tudo isso é contrato. Mudar um
   contrato sem coordenar com consumidores quebra produção.

4. **Não tome decisões arquiteturais grandes sem registrar a motivação.**
   Substituir uma biblioteca, mudar o padrão de cache, introduzir um novo
   protocolo — isso exige um ADR (`docs/decisions/adr-XXXX.md`) ou, no
   mínimo, uma justificativa explícita no PR.

5. **Priorize mudanças pequenas, rastreáveis e reversíveis.**
   Um PR pequeno é fácil de revisar, fácil de reverter e fácil de bissecar
   quando dá problema. Um PR de 2.000 linhas alterando 50 arquivos é um risco.

6. **Respeite os padrões existentes do repositório.**
   Se o repo usa `snake_case`, não introduza `camelCase`. Se o repo usa
   `pytest`, não introduza `unittest`. Se o repo usa `httpx`, não introduza
   `requests`. Padrão local sempre vence preferência pessoal do agente.

---

## 2. Proibições explícitas

O agente **NÃO PODE** fazer nenhum dos itens abaixo. Esta lista não é exaustiva,
mas cobre os erros mais frequentes observados em PRs gerados por IA.

| # | Proibição | Por quê |
|---|-----------|---------|
| 1 | Criar classes, abstrações, enums, helpers, factories ou services **desnecessários** | Abstração prematura é dívida técnica imediata |
| 2 | Criar **fallback silencioso** para "fazer funcionar" | Esconde falhas reais; retarda a detecção de bugs em produção |
| 3 | **Chumbar** valores, credenciais, URLs, tokens, IDs, datas ou configurações | Quebra reproduzibilidade e expõe segredos |
| 4 | Resolver problemas de **backend no frontend** quando a responsabilidade é do backend | Solução errada na camada errada; dificulta manutenção |
| 5 | Resolver problemas de **frontend no backend** quando a responsabilidade é do frontend | Mistura de responsabilidades; vaza UX para a API |
| 6 | Ignorar erros de integração com **try/except genérico** sem tratamento correto | Engole exceções, bloqueia observabilidade |
| 7 | Criar **mocks em código produtivo** para contornar falha de serviço | Mock em produção mascara problemas reais |
| 8 | Alterar contratos entre serviços sem **atualizar consumidores, documentação e testes** | Quebra cadeia de dependências em produção |
| 9 | **Duplicar lógica** já existente | Mantém duas verdades divergentes; bug aparece em uma e não em outra |
| 10 | **Misturar responsabilidades** entre camadas | Viola arquitetura; impede testes isolados |
| 11 | Criar código **temporário** sem marcação, issue ou plano de remoção | Código "temporário" vira permanente em 100% dos casos |
| 12 | **Apagar testes** para fazer o build passar | Esconde regressão; engana o pipeline |
| 13 | **Reduzir validações, segurança ou observabilidade** para resolver bugs rapidamente | Cria vulnerabilidades e cegueira operacional |
| 14 | Criar **dependências novas** sem justificativa | Aumenta supply chain risk e tempo de build |
| 15 | Fazer **refatorações amplas** sem necessidade direta da tarefa | Polui o diff; dificulta revisão |
| 16 | Pular hooks de pré-commit ou CI (`--no-verify`, `--skip-tests`) | Hooks existem por motivo; pulá-los é violação |
| 17 | Modificar `.gitignore`, `.editorconfig`, `pyproject.toml`, `package.json` sem necessidade da tarefa | Mudanças em config compartilhada afetam todo o time |
| 18 | Trocar nomes de variáveis, símbolos ou arquivos por **preferência estética** | Causa conflitos de merge sem ganho real |

> **Regra de ouro**: se você está prestes a fazer algo desta lista, **pare** e
> pergunte ao humano. Há sempre uma alternativa correta — e ela passa por
> entender melhor o problema, não por contornar a regra.

---

## 3. Responsabilidade por camada

Cada camada tem responsabilidades claras. **Não cruze fronteiras** sem justificativa.

### 3.1 Frontend

O frontend é um **consumidor** dos contratos definidos pelo backend. Ele não
inventa regras de negócio.

**Deve:**
- Consumir contratos definidos pelo backend (REST, WebSocket, GraphQL).
- Exibir erros de forma clara, **usando os padrões existentes** de componente
  de erro do projeto.
- Validar entrada do usuário **localmente** (UX, feedback rápido), mas **nunca
  como única validação** — o backend valida sempre.
- Tratar estados de loading, erro, vazio e sucesso de forma explícita.

**Não pode:**
- Inventar regras de negócio que pertencem ao backend (ex.: calcular impostos,
  decidir permissões, aplicar descontos).
- Criar tratamento artificial para **esconder erro de API** (`try/catch` que
  retorna estado "feliz" quando a API falha).
- Manter cópia local de dados que pertencem ao backend, fora do padrão de
  cache do projeto (ex.: state global com dados de billing duplicados).
- Hardcoded de URLs de API, IDs de tenant, IDs de feature flag — tudo deve
  vir de configuração.

```typescript
// ERRADO: esconder erro do backend no frontend
try {
  const order = await api.createOrder(payload);
  return order;
} catch {
  return { id: -1, status: "pending" };  // estado falso, esconde falha real
}

// CORRETO: propagar erro com contexto, deixar UI tratar
try {
  return await api.createOrder(payload);
} catch (err) {
  throw new OrderCreationError(err.message, { cause: err });
}
```

```typescript
// ERRADO: regra de negócio no frontend
const totalComDesconto = subtotal * (cliente.tipo === "VIP" ? 0.9 : 1.0);

// CORRETO: backend retorna o total já calculado
const { total, descontoAplicado } = await api.calcularTotal(carrinho);
```

### 3.2 Backend

O backend é a **fonte da verdade** para regras de negócio, validações e contratos.

**Deve:**
- Ser a **fonte primária** das regras de negócio.
- **Validar** toda entrada (Pydantic, Zod, etc.) e toda saída.
- Expor **erros estruturados** com código, mensagem e contexto
  (`{"error": "INVALID_TENANT", "message": "...", "detail": {...}}`).
- Manter **contratos estáveis**. Mudanças breaking exigem versionamento.
- Logar operações relevantes com `request_id`, `tenant_id`, `user_id` para
  correlação.

**Não pode:**
- Devolver respostas com **lógica específica de tela** (ex.: "ocultar este
  botão", "mostrar este alerta vermelho"). Isso é responsabilidade do frontend.
- Retornar `200 OK` com `{"success": false}` no payload. Use o status HTTP
  corretamente: `4xx` para erros do cliente, `5xx` para erros do servidor.
- Usar **try/except genérico** que engole exceção. Capture exceções específicas
  e re-lance ou registre.
- Hardcoded de URLs de outros serviços, credenciais, chaves de API — tudo
  vem de `config.py` (ou equivalente).

```python
# ERRADO: lógica específica de tela no backend
return {"items": items, "show_pagination": len(items) > 10}

# CORRETO: backend retorna dados; frontend decide apresentação
return {"items": items, "total": total}
```

```python
# ERRADO: try/except genérico que engole tudo
try:
    return await external_api.call(...)
except Exception:
    return None   # erro silenciado

# CORRETO: capturar exceções específicas, propagar contexto
try:
    return await external_api.call(...)
except ExternalAPITimeout as exc:
    logger.warning("external_api_timeout", extra={"endpoint": "..."})
    raise IntegrationClientError("external_api timeout", cause=exc)
except ExternalAPIServerError as exc:
    logger.error("external_api_5xx", extra={"endpoint": "..."})
    raise IntegrationClientError("external_api 5xx", cause=exc)
```

### 3.3 Banco de dados

O schema do banco é uma **interface pública** do serviço. Mudanças seguem
processo formal.

**Deve:**
- Toda mudança de schema vira **migration** (Alembic, Flyway, equivalente).
- Migrations são **idempotentes** (`IF NOT EXISTS`, `IF EXISTS`).
- Mudanças destrutivas (drop column, drop table, rename) têm **plano de
  rollback** documentado.
- Toda tabela respeita as **convenções de auditoria** do ecossistema
  (`created_at`, `updated_at`, `created_by`, `updated_by`, `is_deleted`,
  `is_active`, `scope`). Para o template Python/FastAPI, ver §27.

**Não pode:**
- Alterar schema sem migration.
- Fazer alteração destrutiva sem plano de rollback.
- **Hardcoded de dados** para "compensar" falha de modelagem
  (ex.: `if user_id == 42: bypass`).
- Modificar dados em produção via SQL ad-hoc fora de migration ou processo
  formal.

```sql
-- ERRADO: mudança destrutiva sem rollback claro
DROP COLUMN antigo_campo;

-- CORRETO: deprecação em duas fases
-- Fase 1: parar de escrever no campo, manter coluna por 1+ release
-- Fase 2: drop column após confirmar que nenhum cliente lê mais
ALTER TABLE x ADD COLUMN antigo_campo_deprecated BOOLEAN DEFAULT TRUE;
-- (depois, em PR separado, após validação)
ALTER TABLE x DROP COLUMN antigo_campo;
```

### 3.4 Integrações

Toda chamada para outro serviço (interno ou externo) é **pontos de falha**.

**Deve:**
- Falhas devem ser **tratadas explicitamente** — nunca silenciadas.
- Usar **timeouts**, **retries** e **circuit breakers** seguindo padrão definido
  do projeto (geralmente `BaseAsyncClient` de `platform_core` no template
  Python/FastAPI — ver §17).
- Logar `service`, `endpoint`, `latency`, `status_code`, `request_id` em todas
  as chamadas.
- Métricas por integração (Prometheus, OTEL).

**Não pode:**
- Criar **bypass de integração** sem aprovação ("se a API falhar, retorna mock").
- Implementar **fallback silencioso** que retorna dados falsos sem logar.
- Esconder timeouts retornando `None`.
- Usar timeout `None` (infinito).

```python
# ERRADO: bypass silencioso de integração
async def get_user(user_id: int):
    try:
        return await auth_client.get_user(user_id)
    except Exception:
        return {"id": user_id, "name": "unknown"}   # mock em produção

# CORRETO: tratar timeout, propagar erro com contexto
async def get_user(user_id: int):
    try:
        return await auth_client.get_user(user_id, timeout=2.0)
    except httpx.TimeoutException as exc:
        logger.warning("auth_timeout", extra={"user_id": user_id})
        raise IntegrationClientError("auth timeout") from exc
```

---

## 4. Regras para fallback

Fallback é **permitido**, mas só sob condições estritas. **Fallback silencioso é
proibido em qualquer circunstância.**

Um fallback só é permitido quando **todos** os 6 critérios abaixo estão
satisfeitos:

| # | Critério | Verificação |
|---|----------|-------------|
| 1 | Existe **requisito funcional claro** documentado | Issue, ADR ou doc do produto descreve o cenário |
| 2 | O **comportamento do fallback** está documentado | README/API_CONTRACT diz o que acontece quando o fallback é acionado |
| 3 | Existe **log estruturado ou métrica** indicando que o fallback foi acionado | `logger.warning("fallback_triggered", extra={...})` ou contador Prometheus |
| 4 | O fallback **não mascara falhas críticas** (auth, billing, dados financeiros, integridade de dados) | Revisão explícita confirma que o caminho crítico não é encoberto |
| 5 | Existe **teste cobrindo o cenário de fallback** | Teste unitário ou de integração executa o caminho de fallback |
| 6 | Se for **temporário**, existe estratégia de remoção | Issue/ticket criado, prazo definido, mencionado no PR |

### O que é fallback silencioso (proibido)

```python
# ERRADO: fallback silencioso, sem log, sem métrica, sem teste
async def get_pricing(item_id: int) -> Decimal:
    try:
        return await pricing_service.get(item_id)
    except Exception:
        return Decimal("0.00")   # silencioso e perigoso (preço grátis!)
```

### O que é fallback aceitável

```python
# CORRETO: fallback explícito, logado, métrica, com teste
PRICING_FALLBACK_COUNTER = Counter("pricing_fallback_total", "...")

async def get_pricing(item_id: int) -> Decimal:
    try:
        return await pricing_service.get(item_id, timeout=1.0)
    except (PricingTimeout, PricingUnavailable) as exc:
        logger.warning(
            "pricing_fallback_triggered",
            extra={"item_id": item_id, "reason": exc.__class__.__name__},
        )
        PRICING_FALLBACK_COUNTER.inc()
        # cache local previamente carregado, com TTL e validação de idade
        cached = await pricing_cache.get(item_id)
        if cached is None:
            raise   # se nem o fallback funciona, propaga
        return cached.price
```

### Outros padrões proibidos

- **Mock produtivo**: classe `FakeXClient` usada em produção quando `XClient`
  está indisponível. Mock vive em `tests/`, nunca em `app/` ou `src/`.
- **Valor default sem explicação**: `return data.get("foo", 0)` sem comentário
  ou justificativa. Se `foo` pode estar ausente, isso é um contrato — explicite.
- **Catch-all `except Exception`** dentro de métodos de negócio. Capture exceções
  específicas que você sabe tratar.

---

## 5. Tomada de decisão

Antes de implementar **qualquer mudança**, o agente deve responder
internamente as 8 perguntas abaixo. Estas não são decoração — são o método.

> Esta lista é a versão resumida. Para detalhes e sub-perguntas, use o
> [Pre-Flight Checklist](docs/ai-agents/pre-flight-checklist.md).

1. **Qual é o problema real?**
   Se você não consegue descrevê-lo em uma frase, ainda não entendeu.

2. **Qual camada é responsável por resolver?**
   Frontend, backend, banco, integração, infra? (ver §3)

3. **Existe padrão semelhante no repositório?**
   Antes de criar algo novo, procure. Reuso > criação.

4. **Essa mudança afeta contratos?**
   Schema HTTP, payload Kafka, evento WebSocket, interface pública de lib?

5. **Essa mudança afeta outros serviços?**
   Liste todos os consumidores impactados. Se houver, pare e coordene.

6. **Existe risco de quebrar produção?**
   Breaking change? Migração de dados? Rollback claro?

7. **Preciso atualizar testes, docs ou variáveis de ambiente?**
   `README.md`, `API_CONTRACT.md`, `.env.example`, OpenAPI?

8. **Estou criando algo novo sem necessidade?**
   Abstração prematura, refactor amplo, dependência nova sem justificativa?

> Se qualquer resposta for "não sei", **pare e investigue**. Se qualquer
> resposta indicar risco alto, **pare e escale** (ver §15).

---

## 6. Padrão de execução de tarefas

Toda tarefa de implementação segue este fluxo de 10 passos. **Não pule passos.**

| # | Passo | Saída esperada |
|---|-------|----------------|
| 1 | Ler `README.md`, `AGENTS.md` e documentação relevante do repo | Contexto carregado |
| 2 | Identificar a **arquitetura** do repositório (folder structure, padrões) | Mapa mental do projeto |
| 3 | Mapear os **arquivos diretamente relacionados** à tarefa | Lista de arquivos a tocar |
| 4 | Verificar **padrões existentes** (funções, utilitários, abstrações já presentes) | Decisão: reusar X ou criar Y |
| 5 | Propor a **menor alteração possível** | Plano em texto, validado mentalmente contra §5 |
| 6 | **Implementar** a mudança | Código aplicado |
| 7 | **Atualizar/criar testes** correspondentes | Testes unit/integration |
| 8 | Rodar **validações disponíveis** (lint, type-check, test, build) | Pipeline local verde |
| 9 | **Documentar impactos** (atualizar `README.md`, `API_CONTRACT.md`, ADR, etc.) | Docs atualizadas |
| 10 | Registrar **limitações ou pendências** no relatório final | Relatório no formato `response-template.md` |

### Quando o passo 8 falha

- Lint vermelho? **Corrija** o lint, não desabilite a regra.
- Type-check vermelho? **Corrija** o tipo, não use `# type: ignore`.
- Teste vermelho? **Investigue** se o teste estava errado ou se o código está
  errado. Nunca apague o teste para passar (ver Proibição #12 em §2).
- Build vermelho? **Investigue** o erro raiz. Não desligue o `strict mode`
  para "fazer compilar".

### Quando você não consegue terminar

Se uma tarefa exige conhecimento que você não tem, dependência externa que você
não pode acessar, ou mudança em escopo que você não tem mandato para fazer:
**pare**, escreva o que conseguiu fazer, o que falta, e por quê. Use o formato
[response-template.md](docs/ai-agents/response-template.md) — em particular as
seções 6, 8 e 9.

### Ferramentas MCP — protocolo obrigatório

Os MCPs encapsulam operações de infra, deploy, governança e qualidade. **Prefira sempre
o MCP** em vez de alternativas manuais. Referência completa de tools e namespaces:
[docs/ai-agents/mcp-reference.md](docs/ai-agents/mcp-reference.md).

#### MCPs disponíveis

| MCP | Domínio | Porta |
|-----|---------|-------|
| `agent-twin-mcp` | Autenticação, perfil, contexto git/OS — **chame `authenticate` PRIMEIRO** | 7098 |
| `config-mcp` | Credenciais, env vars por perfil/tenant, hardware | 7099 |
| `deploy-mcp` | Git, commits, PRs, GitHub Actions, ACR | — |
| `docs-mcp` | Geração, validação e auditoria de documentação | — |
| `qa-mcp` | Testes, lint, type-check, security scan | — |
| `infra-mcp` / `ai-governance-mcp` | Governança, ADRs, políticas | — |
| `services-mcp` | Registro e health de serviços/containers | — |
| `session-mcp` | Sessões, checkpoints, artefatos | — |

**Regras:** (1) Use MCP antes do equivalente manual. (2) `ToolSearch("select:mcp__<srv>__<tool>")` antes de invocar. (3) Nunca presuma parâmetros. (4) Erros retornam `{"error":"...","details":"..."}`.

---

## 7. Múltiplos agentes

O ecossistema tem ~35 repositórios e múltiplos agentes (Claude, Cursor, Copilot,
agentes internos) atuando em paralelo. Coordenação é responsabilidade de cada
agente.

### Regras de não-conflito

1. **Atue apenas no seu repositório ou escopo definido.**
   Se você foi invocado para `platform-orders`, não toque em `platform-billing`
   sem um motivo direto e justificável (ex.: PR coordenado de mudança de
   contrato).

2. **Não modifique arquivos de outro domínio sem necessidade explícita.**
   Mudar um arquivo `frontend/components/Foo.tsx` enquanto a tarefa é de
   backend é violação.

3. **Não altere contratos compartilhados sem coordenação.**
   Schemas em libs `platform-*-lib`, `src/platform_{service}/`, ou `api-contracts/`
   são compartilhados. Mudanças exigem PR coordenado em cada consumidor.

4. **Não duplique implementação feita por outro serviço.**
   Antes de criar `MyEmailSender`, verifique se já existe `platform-notify`
   ou similar no ecossistema. Reuso entre serviços vai por bibliotecas e clientes
   tipados (ver §17 e §20).

5. **Registre mudanças que impactam outros times ou agentes.**
   Use a Seção 7 do [response-template.md](docs/ai-agents/response-template.md)
   para listar todos os serviços impactados e ações requeridas.

6. **Quando houver dependência entre serviços, documente claramente o contrato esperado.**
   API stub, schema OpenAPI compartilhado, ADR cruzado. O agente não pode
   assumir que outro time vai "adivinhar" o que mudou.

### Conflito de PR entre agentes

Se você abre um PR e o `git fetch` mostra que outro agente tocou nos mesmos
arquivos:

- **Pare**. Não force merge.
- Avalie se as mudanças são compatíveis. Se sim, faça o rebase com cuidado.
- Se forem incompatíveis, **escale** ao humano para decidir a ordem dos PRs.
- Nunca apague o trabalho do outro agente para "limpar conflito".

---

## 8. Contratos e APIs

Contratos são a **interface pública** entre serviços. Mudanças seguem regras
estritas.

### 8.1 Versionamento

- **REST**: prefixo `/v1`, `/v2` no path. Quebra de contrato exige nova versão.
- **Kafka**: campo `schema_version` no payload, ou novo tópico (ex.:
  `orders.created.v2`).
- **WebSocket**: campo `version` no payload de handshake ou no envelope.
- **Libs internas (`platform-*-lib`, `src/platform_{service}/`)**: SemVer
  (`MAJOR.MINOR.PATCH`). Breaking change = bump major.

### 8.2 Compatibilidade retroativa

Mudanças **aditivas** (campo opcional novo, novo endpoint, novo evento) são
seguras e não exigem nova versão.

Mudanças **breaking** (renomear campo, remover endpoint, mudar tipo, mudar
semântica) exigem:
- Nova versão (path, tópico, ou major bump).
- Versão antiga mantida por período de deprecação acordado.
- Comunicação a todos os consumidores conhecidos.
- ADR registrando a decisão.

### 8.3 Schemas de request/response

- Definir com **schema validado** (Pydantic, Zod, JSON Schema, Protobuf).
- Validar **na borda** (entrada e saída do serviço), não no meio do código.
- `additionalProperties: false` por padrão em request schemas — rejeitar
  campos desconhecidos.

### 8.4 Mensagens de erro padronizadas

Use o formato canônico do ecossistema:

```json
{
  "error": "ERROR_CODE_UPPER_SNAKE",
  "message": "Mensagem legível para humanos.",
  "detail": {
    "field": "email",
    "value": "..."
  },
  "request_id": "uuid4-string"
}
```

- `error`: enum, machine-readable, estável (não muda entre versões).
- `message`: legível, pode mudar entre versões.
- `detail`: opcional, contexto adicional.
- `request_id`: sempre presente para correlação com logs.

### 8.5 OpenAPI/Swagger (quando aplicável)

- Toda API REST exposta deve ter um schema OpenAPI **completo e atualizado**.
- Toda rota tem `summary`, `description`, `responses`, `operation_id` único.
- Todo schema tem `description` em cada campo e `example` no schema.
- Para o template Python/FastAPI, ver §24.

### 8.6 Testes de contrato

- Quando aplicável (Pact, schemathesis, Spectator), manter testes de contrato
  automatizados entre produtor e consumidor.
- No mínimo, snapshot do schema OpenAPI commitado e diff em CI (ver §43).

---

## 9. Configuração e ambiente

Configuração nunca é código. Código nunca é configuração.

### Proibições

| # | Proibição | Por quê |
|---|-----------|---------|
| 1 | **Chumbar configuração** no código (URLs, IDs, chaves, timeouts) | Quebra entre ambientes, expõe segredos |
| 2 | Criar `.env` com **segredos reais** versionados | Vaza credenciais; usar `.env.example` com placeholders |
| 3 | **Remover validação** de variável obrigatória | Falhas silenciosas em produção |
| 4 | Trocar **endpoint produtivo por mock** ou stub | Provoca incidentes |
| 5 | Criar **configuração paralela** fora do padrão do projeto | Duas fontes de verdade divergem com o tempo |

### Padrões aceitos

- `.env.example` na raiz, sem valores secretos, apenas chaves e exemplos
  inócuos (`API_KEY=changeme`).
- `config.py` (Python), `config.ts` (Node), ou equivalente, lendo do ambiente
  via `pydantic-settings`, `dotenv`, etc.
- **Validação de carga**: o serviço deve **falhar no startup** se uma variável
  obrigatória estiver ausente (não silenciosamente usar `None`).
- Secrets em ambiente: K8s `Secret`, AWS Secrets Manager, Vault. Nunca em
  `ConfigMap`, `.env` versionado ou imagem Docker.

### Variáveis de ambiente comuns

Para alinhamento, use estes nomes quando aplicável:

| Variável | Propósito |
|----------|-----------|
| `ENVIRONMENT` | `development` / `staging` / `production` |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `DB_DSN` ou `DATABASE_URL` | DSN completo do banco |
| `KAFKA_BOOTSTRAP_SERVERS` | Hosts do Kafka |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Endpoint OTLP |
| `SENTRY_DSN` | DSN do Sentry |
| `SERVICE_ID` | Identificador do serviço (ex.: `platform-orders`) |
| `INTERNAL_API_TOKEN` | Token para chamadas internas backend-to-backend |

---

## 10. Observabilidade

Sem observabilidade, é impossível operar. Toda mudança preserva ou melhora a
visibilidade do sistema.

### Logs

- **Estruturados** (JSON), não texto livre.
- Campos obrigatórios: `timestamp`, `level`, `message`, `request_id`,
  `service_id`. Quando aplicável: `tenant_id`, `user_id`, `trace_id`.
- Use níveis corretamente:
  - `DEBUG`: detalhes para investigação local
  - `INFO`: eventos de negócio relevantes (operação completada, fallback acionado)
  - `WARNING`: situação degradada mas tratada (retry, fallback, latência alta)
  - `ERROR`: falha que precisa de atenção (exceção propagada, integração quebrada)
  - `CRITICAL`: falha que precisa de ação imediata (corrupção de dados, segurança)
- **Não logue dados sensíveis**: senhas, tokens, PII completa, números de cartão.

### Métricas

- Padrão Prometheus / OTEL.
- **Métricas mínimas por endpoint**: contador de requests, histograma de
  latência, contador de erros.
- **Métricas mínimas por integração**: contador de chamadas, latência,
  taxa de erro, fallbacks acionados.
- **Métricas de negócio**: aplicáveis (orders/min, signups/dia, etc.).

### Rastreamento (tracing)

- OTEL distribuído. Toda chamada cross-service propaga `traceparent`.
- Spans nomeados com convenção: `{service}.{operation}` (ex.: `orders.create`,
  `auth.validate_token`).

### Correlação entre serviços

- **`request_id`**: gerado na borda (gateway / primeiro serviço), propagado em
  todas as chamadas via header `X-Request-ID`.
- **`trace_id`**: gerado pelo OTEL, propagado via `traceparent`.

### Não engolir exceções

Toda exceção que não é tratada deve **subir** com contexto. `try/except` sem
log e sem re-raise é proibido (ver §3.2 e §4).

### Não remover logs importantes

Se um log existe e tem nível `INFO+`, ele provavelmente está sendo usado em
dashboards, alertas ou investigações. **Não remova** sem confirmar com o time
responsável.

---

## 11. Segurança

Segurança é não-negociável. Nenhuma "rapidez" justifica reduzir controles.

### Proibições

| # | Proibição |
|---|-----------|
| 1 | **Expor segredos** no código, em logs, em mensagens de erro, em traces |
| 2 | **Reduzir autenticação ou autorização** para resolver bugs (ex.: comentar `@require_auth`) |
| 3 | **Remover validação de permissões** ("o frontend já valida") |
| 4 | **Logar dados sensíveis** (senhas, tokens, PII completa, números de cartão, chaves) |
| 5 | Criar **bypass de segurança** (`if user_id == 1: skip_auth`) |
| 6 | Instalar **dependência insegura** sem análise (CVE conhecida, abandonware, autor desconhecido) |
| 7 | Aceitar **input não validado** em queries SQL, comandos shell, paths de arquivo, `eval`, etc. |
| 8 | Desabilitar TLS, validação de certificado, ou políticas de CORS em produção |
| 9 | Commitar `.env`, `.pem`, `.key`, `credentials.json`, `service-account*.json` |
| 10 | Usar `MD5`/`SHA1` para qualquer coisa relacionada a segurança (use `bcrypt`/`argon2` para senhas, `SHA256+` para hashes) |

### Práticas obrigatórias

- **Validação de entrada** em toda borda: schemas, sanitização, escape.
- **Princípio do menor privilégio**: o serviço só tem acesso ao que precisa.
- **Auth e Z** explícitas: cada endpoint declara explicitamente quem pode chamar.
- **Rate limiting** em endpoints públicos.
- **Headers de segurança**: HSTS, CSP, X-Content-Type-Options, X-Frame-Options
  (no template Python/FastAPI, vem de `platform_observability` — ver §22).
- **Scan de dependências**: `pip-audit`, `npm audit`, `trivy` no CI.
- **Scan de segredos**: `gitleaks`, `trufflehog` antes de commit.

### Reportar vulnerabilidade

Se você encontrar uma vulnerabilidade de segurança durante a tarefa (mesmo que
não relacionada à tarefa em si), **escale imediatamente** ao humano. Não
publique, não comente em PR público, não tente "consertar de carona". Veja §15.

---

## 12. Testes

Toda mudança relevante considera as 4 categorias abaixo. **Apagar ou enfraquecer
testes existentes é violação grave** (ver Proibição #12 em §2).

### 12.1 Categorias

| Categoria | Cobre | Exemplos |
|-----------|-------|----------|
| **Unitário** | Função/método isolado | `pytest tests/unit/`, `vitest`, `jest` |
| **Integração** | Múltiplos componentes do mesmo serviço (DB, cache, fila) | `pytest tests/integration/` com PostgreSQL real |
| **Contrato** | Interface entre serviços (API, eventos) | Pact, schemathesis, snapshot OpenAPI |
| **End-to-end** | Fluxo completo do usuário | Playwright, Cypress, k6, scripts de smoke |

### 12.2 Quando criar/atualizar cada tipo

- **Unit**: para toda função/método novo ou modificado com lógica não trivial.
- **Integração**: para todo módulo novo, todo handler de evento, toda nova
  query de banco.
- **Contrato**: para toda mudança de schema HTTP/Kafka/WebSocket exposto.
- **E2E**: para fluxos críticos (login, checkout, criação de tenant) — atualizar
  quando o fluxo muda.

### 12.3 Coverage

Cada serviço define sua meta. No template Python/FastAPI, mínimo de **70%** é
enforçado em CI (ver §34).

### 12.4 Fixtures e dados

- Não criar fixtures duplicadas; reusar `conftest.py`.
- Não usar dados reais de produção (PII, credenciais).
- Não depender de **ordem** entre testes; cada teste é isolado.
- Não depender de **rede externa** em testes unitários (use mocks).
- Em testes de integração, use containers (Testcontainers, docker-compose).

### 12.5 Anti-patterns em testes

```python
# ERRADO: apagar teste para passar pipeline
- def test_user_cannot_see_other_tenant():
-     ...

# ERRADO: enfraquecer asserção
- assert response.status_code == 200
+ assert response.status_code in (200, 500)   # nunca

# ERRADO: pular teste em CI sem motivo
@pytest.mark.skip(reason="flaky")   # corrija o flake, não pule
def test_critical_path(): ...

# ERRADO: mock que sempre passa
mock_payment.return_value = MagicMock(status="success")
# (sem assertar que o mock foi chamado com os argumentos certos)
```

---

## 13. Formato obrigatório de resposta

Ao concluir qualquer tarefa de implementação, o agente deve produzir um
relatório seguindo o formato canônico definido em
[docs/ai-agents/response-template.md](docs/ai-agents/response-template.md).

O relatório obrigatoriamente cobre:

| Seção | Conteúdo |
|-------|----------|
| 1. O que foi alterado | Lista objetiva, 1 linha por mudança |
| 2. Por que foi alterado | Motivação direta — bug, feature, refactor |
| 3. Arquivos modificados | Tabela com tipo (modificado/criado/removido) |
| 4. Riscos | Tabela com probabilidade, impacto, mitigação |
| 5. Testes executados | Lista marcável com resultado |
| 6. Testes não executados (e motivo) | Honesto sobre o que ficou de fora |
| 7. Impacto em outros serviços | Lista cross-service |
| 8. Documentação atualizada | Lista marcável |
| 9. Pendências e recomendações | Follow-ups |
| 10. Decisões arquiteturais | Justificar escolhas não triviais |

> Não pular seções. Se uma seção não se aplica, escrever "Não se aplica" com
> uma linha de justificativa.

> Marcar como executado o que não foi executado é violação grave. Ver §15
> (HARD STOPS) e o anti-exemplo no `response-template.md`.

---

## 14. Checklist final obrigatório

Antes de concluir qualquer tarefa, o agente confirma os 11 itens abaixo.
Use isto como gate de saída — não declare a tarefa como pronta sem percorrê-lo.

- [ ] Li o `AGENTS.md` (Parte I e Parte II quando aplicável).
- [ ] Entendi a arquitetura do repositório.
- [ ] Alterei apenas arquivos necessários ao escopo da tarefa.
- [ ] Não criei abstrações desnecessárias.
- [ ] Não criei fallback silencioso (todos os fallbacks atendem aos 6 critérios de §4).
- [ ] Não chumbei valores, credenciais, URLs, IDs ou datas.
- [ ] Respeitei separação frontend/backend/banco/integração (§3).
- [ ] Mantive contratos compatíveis (ou abri PRs coordenados se breaking).
- [ ] Atualizei testes quando necessário (§12).
- [ ] Rodei validações disponíveis (lint, type-check, test, build).
- [ ] Documentei riscos e impactos no formato `response-template.md` (§13).

> Se você marcou `[x]` em qualquer item sem ter feito de fato, isso é violação
> de §15 (HARD STOPS).

---

## 15. HARD STOPS — quando parar e escalar

Existem situações em que o agente deve **parar imediatamente** e devolver o
controle ao humano. Não tente "achar uma volta", não tente "implementar
parcialmente". **Pare, reporte, espere instrução.**

### Lista de hard stops

| # | Situação | Ação |
|---|----------|------|
| 1 | A tarefa exige modificar um repositório `platform-*-lib` privado | Parar. Abrir LIB CHANGE REQUEST (ver §18). Aguardar aprovação de `@caiog` |
| 2 | A mudança quebra contrato consumido por outros serviços e você não tem mandato para coordenar | Parar. Listar consumidores. Pedir mandato ao humano |
| 3 | A solução requer apagar testes, baixar cobertura, ou pular pipeline (`--no-verify`) | Parar. Investigar causa raiz. Não contornar |
| 4 | A solução requer fallback silencioso, mock produtivo, ou hardcoded | Parar. Reformular abordagem |
| 5 | Você não consegue justificar a mudança contra uma regra existente | Parar. Pedir clarificação ao humano |
| 6 | Você encontrou uma vulnerabilidade de segurança (mesmo fora do escopo) | Parar. Escalar privadamente. Não publicar |
| 7 | A mudança envolve dados em produção (UPDATE/DELETE direto, sem migration) | Parar. Pedir aprovação explícita |
| 8 | A mudança requer credenciais de produção que você não tem | Parar. Não tente adivinhar |
| 9 | O ambiente local está em estado inesperado (branch desconhecido, arquivos não rastreados) | Parar. Investigar antes de tomar ações destrutivas |
| 10 | Você detecta que outro agente já está trabalhando nos mesmos arquivos | Parar. Coordenar via humano |
| 11 | A tarefa exige decisão arquitetural sem ADR ou orientação prévia | Parar. Propor abordagem. Pedir validação |

### Como reportar um hard stop

Use este formato:

```markdown
# HARD STOP — {tipo do bloqueio}

## Situação
{1–2 frases descrevendo o que motivou o stop}

## Por que parei
{regra do AGENTS.md ou risco identificado}

## O que foi feito até aqui
{lista de mudanças aplicadas — se nenhuma, escrever "Nenhuma"}

## O que precisa de decisão humana
{pergunta clara, com opções viáveis se possível}

## Impacto de continuar errado
{o que aconteceria se eu seguisse sem aprovação}
```

### Escalação para `@caiog`

Mudanças em `platform-*-lib` privadas seguem o template específico em §18.
Outras escalações vão para o humano que invocou o agente. Em ambos os casos,
**aguarde resposta** antes de continuar.

---

# PARTE II — Padrões técnicos do template Python/FastAPI

> Esta parte aplica-se ao `platform-service-template` e a todos os serviços
> derivados dele (`platform-analytics`, `platform-cdc`, `platform-cloud`,
> `platform-connectors`, `platform-governance`, `platform-ml`,
> `platform-scheduler`, `platform-monitor`, `platform-docextract`,
> `platform-dataquality` e quaisquer novos).
>
> Frontends, libs JS e ferramentas em outras linguagens **não** seguem a Parte II
> — apenas a Parte I, somada ao seu próprio AGENTS.md local.

---

## 16. Sobre este template

Este é o template canônico de microserviço da plataforma `dataforalltech`.
Todo serviço da plataforma é derivado dele ou deve ser atualizado para alinhar.

**Filosofia**: lógica de negócio vive em `app/modules/`. Infraestrutura vem
de pip libs privadas. O template controla apenas o que é genuinamente
específico do serviço.

**Serviços que usam este template** (lista pode ter crescido):
`platform-analytics`, `platform-cdc`, `platform-cloud`, `platform-connectors`,
`platform-governance`, `platform-ml`, `platform-scheduler`, `platform-monitor`,
`platform-docextract`, `platform-dataquality`.

---

## 17. Mapa de bibliotecas privadas

**Nunca copie código de lib inline para um serviço.** Sempre importe da lib.

| Import Python | Pacote pip | Conteúdo |
|---------------|-----------|----------|
| `platform_core` | `platform-core-lib` | `BaseRepository`, `BaseService`, `BaseAsyncClient`, `DatabasePool`, exceptions, `request_context`, constants, enums, interfaces, mappers, i18n, tz, logging |
| `platform_auth` | `platform-auth-lib` | JWT manager, `decode_token`, criptografia de credenciais, permissões de módulo |
| `platform_events` | `platform-events-lib` | `KafkaEventBus`, `ConsumerManager`, `@handle_event`, `@emit_event`, `bus_config`, schemas tipados de eventos |
| `platform_observability` | `platform-observability-lib` | Setup OTEL, setup Sentry, limiter (slowapi), security headers, request size middleware |
| `platform_tenant` | `platform-tenant-lib` | `TenantMiddleware`, `TenantManager`, tenant provisioner |
| `platform_files` | `platform-files-lib` | Protocolo `FileStore`, `LocalFileStore`, `S3FileStore`, `FileParserFactory` (csv/excel/json/parquet/xml), `ExportRepository` |
| `platform_log` | `platform-log-lib` | `BaseLogRepository`, schemas de log de operação (12 tipos de domínio), `ReportViewLog`, `DownloadLog`, `SlowRequestLogMiddleware` |
| `platform_data_types` | `platform-data-types-lib` | `DataTypeWrangler` (mapeamento canônico de tipos entre engines de DB) |
| `platform_database` | `platform-database-lib` | `PostgresPool`, `MySQLPool`, `TenantPostgresPool`, `UnitOfWork`, `init_pool`, helpers de migration (sem SQLAlchemy) |
| `platform_ws` | `platform-ws-lib` | `ConnectionManager`, `WSRouter`, `ws_emit`, `ws_push_to_user`, `ws_broadcast`, `register_ws_routers` (opcional — apenas para serviços com WebSocket) |

Instale via SSH (dev local) ou HTTPS+token (CI/CD). Ver `requirements.txt`.

> **SQLAlchemy é PROIBIDO.** Nunca adicione como dependência runtime ou de
> migration. `platform-database-lib` usa `asyncpg`/`aiomysql` (runtime) e
> `psycopg2`/`PyMySQL` (migrations). Alembic é usado APENAS como runner de
> migration — não como ORM.

---

## 18. Governance de bibliotecas privadas

### Quem pode mudar uma lib privada

**APENAS o owner da plataforma (`@caiog`) pode aprovar mudanças em qualquer
repositório `platform-*-lib`.**

Nenhum time de serviço, nenhum agente de IA, nenhum processo automatizado
pode abrir PR, fazer push, ou modificar qualquer arquivo nos seguintes
repositórios sem aprovação explícita por escrito:

```
platform-core-lib        platform-auth-lib        platform-events-lib
platform-observability-lib  platform-tenant-lib   platform-files-lib
platform-log-lib         platform-data-types-lib  platform-database-lib
platform-ws-lib
```

### Para agentes de IA — HARD STOP

Se você é um agente de IA trabalhando em algum microserviço e identifica
necessidade de alterar uma lib privada, você **DEVE**:

1. **PARAR** — não modifique nenhum arquivo dentro de `platform-*-lib`.
2. **DOCUMENTAR** a mudança requerida com contexto completo:
   - Qual lib e qual arquivo precisa mudar.
   - Qual o comportamento atual e qual o desejado.
   - Por que a mudança é necessária (regra de negócio, bug, padrão novo).
   - Quais serviços são afetados.
3. **REPORTAR** ao usuário e aguardar aprovação explícita antes de seguir.
4. **NUNCA** contornar uma limitação da lib duplicando código de lib inline
   no serviço (viola §17 e §39).

### Template de change request

```
LIB CHANGE REQUEST
==================
Library:  platform-{lib}-lib
File:     src/platform_{lib}/algum_modulo.py
Current:  <cole o código atual>
Required: <cole a mudança proposta>
Reason:   <por que é necessário>
Impact:   <quais serviços são afetados e como>
Urgency:  critical | high | medium | low
```

### Versionamento — OBRIGATÓRIO após cada commit em lib

Todo commit mergeado em um repositório `platform-*-lib` **DEVE ser
imediatamente seguido de uma tag git**.
Serviços fixam libs por tag em `requirements.txt` — sem tag, o novo commit
é inalcançável.

#### Convenção de tagging (semver)

| Tipo de mudança | Bump de versão | Exemplo |
|-----------------|----------------|---------|
| Bugfix, atualização de doc, ajuste menor | patch (`z`) | `v0.1.0` → `v0.1.1` |
| Feature nova retro-compatível | minor (`y`) | `v0.1.1` → `v0.2.0` |
| Mudança breaking (interface) | major (`x`) | `v0.2.0` → `v1.0.0` |

#### Passos obrigatórios após cada lib change aprovada

```bash
# 1. Commit da mudança
git commit -m "fix(platform-{lib}-lib): <o que mudou>"

# 2. Tag imediatamente — nunca pule este passo
git tag v0.1.1   # bump no segmento correto (patch/minor/major)

# 3. Push commit e tag juntos
git push origin main --tags

# 4. Atualize requirements.txt em cada serviço afetado
# platform-{lib}-lib @ git+ssh://git@github.com/dataforalltech/platform-{lib}-lib.git@v0.1.1
```

> **Nunca faça push para main sem tag.** Um commit sem tag não pode ser
> fixado em `requirements.txt` e força serviços a usar referência móvel
> (nome de branch), o que quebra builds reproduzíveis.

#### Para agentes — checklist de tagging

Quando aprovado a commitar em uma lib privada:

1. Faça a mudança aprovada.
2. Rode `pytest` — todos os testes devem passar.
3. `git commit -m "..."` no formato acima.
4. Bump de versão em `pyproject.toml` (`version = "0.1.1"`).
5. `git tag v0.1.1`.
6. `git push origin main --tags`.
7. Reporte ao usuário com o nome da tag para que atualize `requirements.txt`
   nos serviços afetados.

### Por que isso importa

Um bug em uma lib privada se propaga para todos os 30+ serviços
simultaneamente. Uma mudança breaking em interface de lib exige migração
coordenada em cada serviço. Toda mudança em lib precisa ser revisada,
versionada, testada e implantada deliberadamente.

---

## 19. Estrutura de diretórios

```
{service-name}/
├── src/
│   └── platform_{service}/            # ← lib instalável (API pública para outros serviços)
│       ├── __init__.py                # Exports públicos: schemas, events, client
│       ├── schemas.py                 # Modelos Pydantic públicos de resposta
│       ├── events.py                  # Payloads tipados de eventos Kafka emitidos
│       └── client.py                  # Cliente HTTP para chamar este serviço (BaseAsyncClient)
├── app/
│   ├── main.py                    # Entry point FastAPI — SEM lógica de negócio
│   ├── consumer.py                # Entry point standalone do consumer Kafka
│   ├── api/
│   │   ├── __init__.py            # Agrega api_router (prefixo /api)
│   │   ├── health.py              # /health/live, /health/ready, /health
│   │   └── v1/__init__.py         # Auto-descobre V1_ROUTERS de todos os módulos
│   ├── core/
│   │   ├── config.py              # Settings (Pydantic BaseSettings) — ESPECÍFICO DO SERVIÇO
│   │   ├── database.py            # Pool de DB concreto (PostgreSQL/MySQL) — ESPECÍFICO
│   │   ├── exceptions.py          # Wrapper fino re-exportando platform_core.exceptions
│   │   └── limiter.py             # Singleton do limiter — importado pelos routers
│   ├── events/
│   │   ├── __init__.py
│   │   └── scrubbers.py           # Scrubbers de PII — ESPECÍFICO DO SERVIÇO (opcional)
│   ├── modules/
│   │   ├── schemas.py             # AuditFieldsMixin, PaginatedResponse[T]
│   │   └── {module}/              # Um diretório por entidade de domínio
│   │       ├── __init__.py        # Exports: V1_ROUTERS, EVENT_HANDLERS
│   │       ├── schemas.py         # {Entity}Create, {Entity}Update + re-exporta {Entity}Response do src/
│   │       ├── repository.py      # SQL — herda BaseRepository
│   │       ├── mappers.py         # dict para Pydantic response
│   │       ├── services.py        # Lógica de negócio — herda BaseService
│   │       ├── routers.py         # Endpoints FastAPI
│   │       └── handlers.py        # @handle_event handlers Kafka
│   └── clients/
│       └── {external}_client.py   # Importa {External}Client de platform_{external}.client
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── alembic/
│   ├── env.py
│   └── versions/                  # Todas as migrations (.py, op.execute() puro SQL)
├── k8s/                           # Manifestos K8s crus
├── helm/platform-service/         # Chart Helm
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                 # Builda src/ como wheel instalável (hatchling)
├── requirements.txt               # Inclui todas as 8 platform-*-lib (+ ws-lib se WebSocket)
├── README.md                      # Obrigatório — usar README do template como base
├── API_CONTRACT.md                # Obrigatório — contrato com frontend (REST, WS, erros)
└── .env.example
```

**Regras:**
- NUNCA adicione arquivos em `app/core/` além de: `config.py`, `database.py`,
  `exceptions.py`, `limiter.py`.
- NUNCA crie `app/observability/` — use `platform_observability` direto.
- NUNCA duplique código de lib — importe da lib.
- `app/events/scrubbers.py` é o ÚNICO arquivo de events que permanece específico.
- `src/platform_{service}/` NÃO PODE importar de `app/` — deve ser auto-contido.
- `app/modules/{module}/schemas.py` re-exporta `{Entity}Response` do `src/` —
  fonte única de verdade.

---

## 20. Service como Library

Todo serviço é **simultaneamente** uma app FastAPI rodando e um pacote pip
instalável.

- `src/platform_{service}/` é a **API pública** — o que outros serviços importam.
- `app/` é a **implementação privada** — nunca importada externamente.

### `src/platform_{service}/schemas.py` — tipos públicos de resposta

```python
from __future__ import annotations
from pydantic import BaseModel

# Auto-contido — SEM imports de app/
class EntityResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
```

### `src/platform_{service}/events.py` — payloads Kafka tipados emitidos pelo serviço

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel

class EntityCreatedEvent(BaseModel):
    event_id: str
    occurred_at: datetime
    tenant_id: str
    service_id: str
    user_id: int | None
    request_id: str
    data: EntityEventData

class EntityEventData(BaseModel):
    id: int
    name: str
    tenant_id: str
```

### `src/platform_{service}/client.py` — cliente HTTP para outros serviços

```python
from __future__ import annotations
from platform_core.base_client import BaseAsyncClient
from platform_{service}.schemas import EntityResponse

class ServiceClient(BaseAsyncClient):
    BASE_PATH = "/api/v1"

    async def get_entity(self, entity_id: int) -> EntityResponse:
        data = await self.get(f"/entities/{entity_id}")
        return EntityResponse(**data)
```

### `src/platform_{service}/__init__.py` — superfície pública

```python
from platform_{service}.client import ServiceClient
from platform_{service}.events import EntityCreatedEvent
from platform_{service}.schemas import EntityResponse

__all__ = ["EntityResponse", "EntityCreatedEvent", "ServiceClient"]
```

### `app/modules/{module}/schemas.py` — re-exporta de src/, adiciona shapes internos

```python
# Re-exporta schema público — fonte única de verdade
from platform_{service}.schemas import EntityResponse as EntityResponse  # noqa: F401

# Shapes só internas (não exportadas pela lib)
class EntityCreate(BaseModel): ...
class EntityUpdate(BaseModel): ...
```

### `app/clients/{external}_client.py` — consumindo lib de outro serviço

```python
# Importe o client da lib do outro serviço, NÃO redefina
from platform_{external}.client import ExternalServiceClient
```

### `pyproject.toml` — configuração dual-mode

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "platform-{service}"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.6.0",
    "httpx>=0.27.0",
    # platform-*-lib são git-only — instaladas via requirements.txt do consumidor
]

[tool.hatch.build.targets.wheel]
packages = ["src/platform_{service}"]
```

### Instalando o serviço como lib em outro serviço

```
# Em platform-governance/requirements.txt — consumindo platform-analytics:
platform-analytics @ git+ssh://git@github.com/dataforalltech/platform-analytics.git@v1.2.0
```

### Dev local — tornar src/ importável dentro do próprio serviço

```bash
# Rode uma vez após clonar, dentro do venv do serviço:
pip install -e .
# Agora `from platform_{service}.schemas import EntityResponse` funciona em app/
```

---

## 21. Regras de import

### Imports corretos em arquivos de módulo (`app/modules/*/`)

```python
# Infraestrutura vinda das libs
from platform_core.base_repository import BaseRepository
from platform_core.base_service import BaseService
from platform_core.base_client import BaseAsyncClient
from platform_core.exceptions import NotFoundError, ConflictError, ValidationError
from platform_auth.jwt_manager import decode_token
from platform_events.decorators import handle_event, EventMetadata
from app.core.limiter import limiter

# Operações de arquivo (apenas em serviços que parseiam arquivos ou rastreiam exports)
from platform_files import FileParserFactory, FileStore
from platform_files import ExportRepository, ExportRecordCreate

# Logs de operação (apenas em serviços que têm tabelas de log)
from platform_log.repository import BaseLogRepository
from platform_log.schemas import ConnectorSetupLog, DataLakeLog  # escolha o schema do domínio

# Nível de serviço — esses arquivos permanecem no serviço
from app.core.config import settings
from app.core.database import DatabasePool, get_pool
from app.core.exceptions import NotFoundError  # re-exportado de platform_core

# Schemas cross-module
from app.modules.schemas import PaginatedResponse, AuditFieldsMixin
```

### Padrões proibidos (esses arquivos não existem mais em `app/core/`)

```python
from app.core.auth import decode_token            # use platform_auth.jwt_manager
from app.core.base_repository import BaseRepository  # use platform_core.base_repository
from app.core.base_service import BaseService        # use platform_core.base_service
from platform_observability.limiter import limiter   # use app.core.limiter (singleton do serviço)
from app.core.request_context import set_auth_header # use platform_core.request_context
from app.core.constants import TENANT_HEADER_NAME    # use platform_core.constants
from app.core.enums import ErrorCode                 # use platform_core.enums
from app.events.decorators import handle_event       # use platform_events.decorators
from app.events.bus_config import bus                # use platform_events.bus_config
from app.observability.otel import setup_otel        # use platform_observability.otel
```

---

## 22. Ordem de middlewares (LIFO)

`FastAPI.add_middleware` é LIFO (Last In, First Out). Registre nesta ordem:

```python
# Registrado por último = executado primeiro
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_SIZE_BYTES)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ALLOWED_ORIGINS, ...)
app.add_middleware(TenantMiddleware)        # pule se não for multi-tenant
app.add_middleware(RequestLoggingMiddleware, temp_folder=settings.LOG_TEMP_FOLDER)

# Decorator HTTP roda antes da pilha de add_middleware
@app.middleware("http")
async def auth_header_context(request, call_next): ...
```

**Regras:**
- `RequestSizeLimitMiddleware` deve ser SEMPRE o mais externo (registrado por último).
- `TenantMiddleware` deve vir DEPOIS de `CORSMiddleware` no registro (para que
  preflights OPTIONS passem).
- `RequestLoggingMiddleware` deve ser o `add_middleware` mais interno.
- `app.state.limiter = limiter` deve ser definido antes de qualquer middleware
  ser registrado.

---

## 23. Padrão de módulo (7 arquivos)

Toda entidade de domínio recebe exatamente UM diretório sob `app/modules/`.

### `__init__.py`

```python
from app.modules.{module}.routers import router
from app.modules.{module}.handlers import EVENT_HANDLERS as _EVENT_HANDLERS
V1_ROUTERS = [router]
EVENT_HANDLERS = _EVENT_HANDLERS
```

### `schemas.py`

```python
from pydantic import BaseModel, ConfigDict, Field
from app.modules.schemas import AuditFieldsMixin
from typing import Optional

class {Entity}Create(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(..., min_length=1, max_length=255)

class {Entity}Update(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str | None = Field(None, min_length=1, max_length=255)

class {Entity}Response(AuditFieldsMixin):
    id: int
    name: str
```

### `repository.py`

```python
from platform_core.base_repository import BaseRepository
from typing import Any, Dict, List, Optional

class {Entity}Repository(BaseRepository):
    TABLE = "{table_name}"
    _UPDATABLE_COLUMNS = frozenset({"field1", "field2"})

    async def get_by_id(self, id: int) -> Optional[Dict[str, Any]]: ...
    async def list_with_count(self, limit: int, offset: int) -> tuple[List[Dict], int]: ...
    async def create(self, data: Dict, id_user: Optional[int] = None) -> int: ...
    async def update(self, id: int, data: Dict, id_user: Optional[int] = None) -> bool: ...
    async def soft_delete(self, id: int, id_user: Optional[int] = None) -> int: ...
```

SQL: sempre use placeholders `$1, $2, ...`. Sempre filtre `WHERE is_deleted = FALSE`.

### `mappers.py`

```python
from typing import Any, Dict
from app.modules.{module}.schemas import {Entity}Response

def to_response(row: Dict[str, Any]) -> {Entity}Response:
    return {Entity}Response(id=row["id"], name=row["name"], ...)
```

### `services.py`

```python
from platform_core.base_service import BaseService
from app.core.exceptions import NotFoundError

class {Entity}Service(BaseService[dict, int]):
    def __init__(self, repo, id_user_ops=None, request_id=None):
        super().__init__(id_user_ops=id_user_ops, request_id=request_id)
        self.repo = repo
    # Sempre use: self._validate_id(), self._log_operation(), self._ensure_found()
```

### `routers.py`

```python
from platform_auth.jwt_manager import decode_token, jwt_manager
from app.core.limiter import limiter
from app.core.database import DatabasePool, get_pool
from fastapi import APIRouter, Depends, Request, status

# jwt_manager é SEMPRE incluído como dependência router-level — sem rotas públicas.
router = APIRouter(
    prefix="/{entities}",
    tags=["{Entities}"],
    dependencies=[Depends(jwt_manager)],   # ← exige Bearer token em TODAS as rotas
)

def _get_service(request: Request, pool: DatabasePool = Depends(get_pool)) -> {Entity}Service:
    # Extrai user do JWT, monta e devolve o service
    ...

@router.get("", response_model=PaginatedResponse[{Entity}Response])
@limiter.limit("120/minute")
async def list_{entities}(request: Request, ..., svc = Depends(_get_service)): ...

@router.post("", response_model={Entity}Response, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_{entity}(request: Request, data: {Entity}Create, svc = Depends(_get_service)): ...
```

### `handlers.py`

```python
from platform_events.decorators import handle_event, EventMetadata
from app.core.database import get_pool

@handle_event(topic="{entity}.create")
async def on_{entity}_create(event: dict, metadata: EventMetadata) -> None:
    # idempotente — Kafka entrega at-least-once
    ...

EVENT_HANDLERS = [on_{entity}_create, ...]
```

---

## 24. Documentação OpenAPI

Todo endpoint e todo schema deve ser totalmente documentado para que o
Swagger UI auto-gerado seja útil ao frontend sem consultar nenhum outro arquivo.

### `app/main.py` — metadados de app (definido uma vez por serviço)

```python
_OPENAPI_TAGS = [
    {"name": "Items", "description": "Operações CRUD para items, escopadas ao tenant autenticado."},
    {"name": "Health", "description": "Probes Kubernetes. Sem autenticação."},
]

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="## Visão geral\n\nAPI REST para **{service-name}**.\n\n## Autenticação\n\n...",
    contact={"name": "Platform Team", "email": "platform@dataforalltech.com"},
    openapi_tags=_OPENAPI_TAGS,
    ...
)
```

Adicione `_custom_openapi()` para injetar security scheme Bearer e lista de servers:

```python
def _custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title=app.title, version=app.version, ...)
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-KEY"},
    }
    schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
    schema["servers"] = [
        {"url": "https://api.dataforalltech.com/{service-name}", "description": "Production"},
        {"url": "http://localhost:8000/{service-name}", "description": "Local"},
    ]
    app.openapi_schema = schema
    return schema

app.openapi = _custom_openapi  # type: ignore[method-assign]
```

### `routers.py` — documentação no nível do endpoint (obrigatório em toda rota)

```python
_RESPONSES_AUTH = {
    401: {"model": ErrorResponse, "description": "Token ausente ou inválido."},
    403: {"model": ErrorResponse, "description": "Permissões insuficientes."},
}
_RESPONSES_RATE  = {429: {"model": ErrorResponse, "description": "Rate limit excedido."}}
_RESPONSES_404   = {404: {"model": ErrorResponse, "description": "Recurso não encontrado."}}
_RESPONSES_422   = {422: {"model": ErrorResponse, "description": "Erro de validação."}}

@router.get(
    "",
    response_model=PaginatedResponse[{Entity}Response],
    summary="List {entities}",
    description="Retorna lista paginada de {entities} ativos para o tenant autenticado.",
    responses={**_RESPONSES_AUTH, **_RESPONSES_RATE},
    operation_id="list{Entities}",          # camelCase, único em todo o serviço
)
@router.post(
    "",
    response_model={Entity}Response,
    status_code=201,
    summary="Create {entity}",
    description="Cria um novo {entity}. Devolve o objeto com `id` atribuído.",
    responses={**_RESPONSES_AUTH, **_RESPONSES_422, 409: {...}, **_RESPONSES_RATE},
    operation_id="create{Entity}",
)
```

**Regras:**
- Toda rota DEVE ter `summary`, `description`, `responses` e `operation_id`.
- `operation_id` deve ser único no serviço (usado para geração de SDK).
- `responses` deve incluir no mínimo: 401, 404 (quando aplicável), 422
  (endpoints de escrita), 429.
- Agrupe responses comuns em dicts `_RESPONSES_*` no topo do arquivo —
  nunca repita inline.

### `schemas.py` — documentação no nível do campo (obrigatório em todo campo)

```python
class {Entity}Create(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"example": {"name": "My item", "category": "finance"}},
    )

    name: str = Field(
        ...,
        min_length=1, max_length=255,
        description="Nome legível. Único dentro do tenant.",
        examples=["My item"],
    )
    category: str | None = Field(
        None,
        max_length=100,
        description="Rótulo opcional de agrupamento.",
        examples=["finance"],
    )
```

**Regras:**
- Todo `Field()` DEVE ter `description`.
- Request bodies DEVEM ter `json_schema_extra` com `example` realista.
- Response schemas DEVEM ter `json_schema_extra` com `example` completo.
- Use `examples=[...]` (lista) em campos individuais; `json_schema_extra={"example": {...}}`
  no model.

### Checklist de validação OpenAPI (rode antes de abrir PR)

```bash
# 1. Swagger UI carrega sem erros
curl -s http://localhost:8000/{service-name}/openapi.json | python -m json.tool > /dev/null && echo "OK"

# 2. Toda rota tem summary e operation_id
python -c "
import json, sys
schema = json.load(open('openapi.json'))
issues = []
for path, methods in schema.get('paths', {}).items():
    for method, op in methods.items():
        if method == 'parameters': continue
        if not op.get('summary'): issues.append(f'Missing summary: {method.upper()} {path}')
        if not op.get('operationId'): issues.append(f'Missing operationId: {method.upper()} {path}')
if issues:
    print('\n'.join(issues)); sys.exit(1)
else:
    print('OK')
"

# 3. Bearer security scheme está presente
python -c "
import json
s = json.load(open('openapi.json'))
assert 'BearerAuth' in s.get('components', {}).get('securitySchemes', {}), 'BearerAuth missing'
print('OK')
"
```

---

## 25. Padrão LogRepository

Use `platform_log` em qualquer serviço que escreve logs de operação na própria
tabela de log. Cada serviço cria sua própria tabela de log via migration Alembic.

### Migration de tabela de log (copie em `alembic/versions/`)

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS {entity}_log (
            id                          SERIAL PRIMARY KEY,
            batch                       VARCHAR(36) NOT NULL,
            -- coluna FK do domínio aqui, ex.:
            -- ida_connector_setup      INTEGER NOT NULL,
            status_process              VARCHAR(50) NOT NULL DEFAULT 'running',
            start_time                  TIMESTAMP,
            end_time                    TIMESTAMP,
            message                     TEXT,
            qty_register                INTEGER,
            size_bytes                  BIGINT,
            idf_cloud_storage_file_log  INTEGER,
            created_at                  TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_{entity}_log_batch ON {entity}_log (batch)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS {entity}_log")
```

### Repository de log (dentro de `app/modules/{module}/repository.py`)

```python
from platform_log.repository import BaseLogRepository

class {Entity}LogRepository(BaseLogRepository):
    TABLE = "{entity}_log"
```

### Uso no service (dentro de `app/modules/{module}/services.py`)

```python
import uuid
from platform_core.tz import utc_now
from platform_log.repository import BaseLogRepository

class {Entity}Service(BaseService[dict, int]):
    def __init__(self, repo, log_repo: BaseLogRepository, id_user_ops=None, request_id=None):
        super().__init__(id_user_ops=id_user_ops, request_id=request_id)
        self.repo = repo
        self.log_repo = log_repo

    async def process(self, entity_id: int) -> dict:
        log_id = await self.log_repo.create_log({
            "batch": str(uuid.uuid4()),
            "ida_{entity}": entity_id,   # FK do domínio
            "status_process": "running",
            "start_time": utc_now(),
        })
        try:
            result = await self.repo.do_work(entity_id)
            await self.log_repo.update_status(log_id, {
                "status_process": "success",
                "end_time": utc_now(),
                "qty_register": result["count"],
            })
            return result
        except Exception as exc:
            await self.log_repo.update_status(log_id, {
                "status_process": "error",
                "end_time": utc_now(),
                "message": str(exc),
            })
            raise
```

### Factory DI no router — injete log repo junto com main repo

```python
def _get_service(request: Request, pool: DatabasePool = Depends(get_pool)) -> {Entity}Service:
    return {Entity}Service(
        repo={Entity}Repository(pool),
        log_repo={Entity}LogRepository(pool),
        id_user_ops=...,
        request_id=getattr(request.state, "request_id", None),
    )
```

### Schemas de response de log

Escolha o schema de domínio que combina com sua entidade em `platform_log.schemas`:

| Schema | Use quando sua entidade é |
|--------|---------------------------|
| `ConnectorSetupLog` | execução de setup de connector |
| `DatabaseQueryLog` | query de connector de database |
| `ConnectorApiSetupLog` | execução de connector de API |
| `DataLakeLog` | processamento de arquivo em datalake |
| `DeliveryLog` | entrega para data warehouse |
| `SchedulerLog` | execução de tarefa do scheduler |
| `MonitorLog` | execução de monitor/alerta |
| `PipelineLog` | execução de pipeline |
| `CloudServerClusterLog` | operação de cluster cloud |
| `DatabaseManagerLog` | operação de schema/migration |

### Middleware de slow-request (adicione em `app/main.py` após `RequestLoggingMiddleware`)

```python
# 5g. Slow-request warning logger (opcional)
from platform_log import SlowRequestLogMiddleware
app.add_middleware(SlowRequestLogMiddleware, threshold_ms=500)
```

---

## 26. Operações de arquivo

Use `platform_files` em serviços que parseiam arquivos estruturados, armazenam
arquivos ou rastreiam exports/downloads.

### Parsing de arquivo — `FileParserFactory`

```python
from platform_files import FileParserFactory

# model_family: "csv" | "excel" | "json" | "parquet" | "xml"
parser = FileParserFactory.create(
    model_family,           # do campo data_model.model_family
    config or {},           # de data_model_csv / data_model_excel / etc.
)

# field_mapping: lista de dicts de data_model_fields
#   [{"name": "col_original", "technical_name": "col_tecnico", "data_type": "string"}, ...]
records = parser.parse(file_bytes, field_mapping)
# records → [{"col_tecnico": "value", ...}, ...]

# Serialize de volta para bytes (ex.: após transformar records)
output_bytes = parser.serialize(records, field_mapping)
```

### Storage de arquivo — `FileStore`

```python
from platform_files import FileStore, FileInfo

# Injete no startup ou por request (depende do backend de storage)
# LocalFileStore é a implementação concreta para uso local/dev:
from platform_files import LocalFileStore

store: FileStore = LocalFileStore(base_path=settings.FILE_STORAGE_PATH)

# Upload
info: FileInfo = await store.upload(file_bytes, filename="report.csv", content_type="text/csv")
cloud_file_id = info.id

# Download
data: bytes = await store.download(cloud_file_id)

# Delete
await store.delete(cloud_file_id)
```

### Tracking de export/download — `ExportRepository`

Cada serviço cria sua tabela `export_records` (copie a SQL de migration do
docstring de `ExportRepository` em `platform_files.exports`).

```python
from platform_files import ExportRepository, ExportRecordCreate

export_repo = ExportRepository(pool)

# Registra um download
export_id = await export_repo.create({
    "id_user": user_id,
    "id_cloud_storage_file": cloud_file_id,
    "session": request_id,
    "family": "report",     # domínio: report | connector | datalake | delivery | pipeline
    "family_id": entity_id,
})

# Lista exports de um user (paginada)
rows, total = await export_repo.list_by_user(user_id, limit=20, offset=0)
```

---

## 27. Convenções de nomenclatura no banco

### Casing de identificadores — por engine

Regra dura aplicável a toda migration, toda query e toda definição de tabela
na plataforma. O casing depende inteiramente do engine de banco.

| Identificador | PostgreSQL | MySQL |
|---------------|-----------|-------|
| Schema / Database | `lowercase` | `UPPERCASE` |
| Tabela | `lowercase` | `UPPERCASE` |
| Coluna | `lowercase` | `lowercase` |

**Exemplos:**

```sql
-- PostgreSQL
CREATE SCHEMA "tenant_550e8400_e29b_41d4_a716_446655440000";
CREATE TABLE items (id SERIAL, name VARCHAR(255), created_by INTEGER);
SELECT id, name, created_by FROM items WHERE is_deleted = FALSE;

-- MySQL
CREATE DATABASE `PLATFORM_DEV`;
CREATE TABLE `ITEMS` (id INT AUTO_INCREMENT, name VARCHAR(255), created_by INT);
SELECT id, name, created_by FROM `ITEMS` WHERE is_deleted = 0;
```

**Regras:**
- Nomes de coluna são SEMPRE lowercase, independente do engine.
- Nomes de tabela MySQL são SEMPRE UPPERCASE — nunca mixed case.
- Identificadores PostgreSQL são SEMPRE lowercase sem aspas — PostgreSQL
  reduz identificadores não-aspeados a lowercase de qualquer forma.
- `self._t()` em `BaseRepository` aplica `table_case` automaticamente — NÃO
  faça uppercase manual em queries; deixe `_t()` cuidar.

### Colunas de auditoria — toda tabela DEVE ter (após colunas de domínio)

| Coluna | Tipo | Default | Descrição |
|--------|------|---------|-----------|
| `id` | SERIAL/AUTO_INCREMENT | — | Primary key |
| `created_by` | INT | NULL | User ID que criou |
| `updated_by` | INT | NULL | User ID da última modificação |
| `created_at` | TIMESTAMP | NOW() UTC | Timestamp de criação (UTC) |
| `updated_at` | TIMESTAMP | NOW() UTC | Timestamp da última modificação (UTC) |
| `is_deleted` | BOOLEAN/TINYINT(1) | FALSE/0 | Flag de soft delete |
| `is_active` | BOOLEAN/TINYINT(1) | TRUE/1 | Estado ativo |
| `scope` | VARCHAR(50) | nome da tabela | Identificador de escopo de auditoria |

**Regras:** NUNCA hard-delete. Sempre `UPDATE ... SET is_deleted = TRUE`.
Todos os timestamps em UTC. Sempre filtre `WHERE is_deleted = FALSE` em reads.

---

## 28. Convenções de queries SQL

### Regra 1 — Colunas devem existir no modelo da plataforma 2.0

Antes de escrever qualquer query SQL em um repository, verifique que toda
coluna referenciada em `SELECT`, `INSERT`, `UPDATE`, `WHERE` ou `ORDER BY`
existe na definição atual da tabela (arquivo de migration em `alembic/versions/`).

**Proibido:**
```python
# ERRADO: referenciar coluna que não existe na migration
await pool.execute("SELECT tenant_code FROM items WHERE id = $1", item_id)
# tenant_code não está na definição da tabela items
```

**Processo correto:**
1. Abra a migration relevante em `alembic/versions/`.
2. Confirme que toda coluna usada na query aparece em `CREATE TABLE`.
3. Se a coluna está faltando, crie nova migration Alembic para adicioná-la —
   nunca assuma.

Quando migrar serviço legacy para novo microserviço, nomes e tipos de colunas
no novo serviço devem ser idênticos ao modelo da plataforma 2.0 (colunas de
auditoria §27). Não carregue nomes legacy como `cod_tenant`, `dt_criacao`,
ou `ativo`.

### Regra 2 — `tenant_id` tem semântica diferente por engine

| Engine | Valor de tenant_id | Namespace usado |
|--------|--------------------|-----------------|
| PostgreSQL | UUID string (`"550e8400-..."`) | schema `tenant_{uuid_underscored}` |
| MySQL | nome do database direto (`"PLATFORM_DEV"`) | database `PLATFORM_DEV` (sem transformação) |

`TenantManager._namespace()` cuida disso automaticamente. **Nunca** chame
`_uuid_to_schema()` ou adicione prefixo `tenant_` manualmente ao trabalhar
com tenants MySQL.

### Regra 4 — Schema deve sempre ser variável em toda query

Toda query SQL que toca uma tabela tenant-scoped DEVE referenciar o schema
via `self._t()` (table resolver do BaseRepository) ou variável explícita de
schema.

**NUNCA hardcoded de schema name em query.**

```python
# ERRADO: schema hardcoded
await pool.execute("SELECT * FROM tenant_42.items WHERE id = $1", item_id)

# ERRADO: nome de tabela sem schema resolution
await pool.execute("SELECT * FROM items WHERE id = $1 AND is_deleted = FALSE", item_id)

# CORRETO: use self._t() — resolve para "{current_schema}"."{table}" em runtime
await pool.execute(
    f"SELECT * FROM {self._t()} WHERE id = $1 AND is_deleted = FALSE",
    item_id,
)

# CORRETO: para joins cross-schema, use self._t() para ambos os lados
await pool.execute(
    f"""
    SELECT i.*, u.email
    FROM {self._t("items")} i
    JOIN public.users u ON u.id = i.created_by
    WHERE i.id = $1 AND i.is_deleted = FALSE
    """,
    item_id,
)
```

`self._t()` é fornecido por `platform_core.base_repository.BaseRepository`.
Lê o ContextVar `tenant_id` setado por `TenantMiddleware` e devolve
`"tenant_{schema_name}"."{table_name}"` para tabelas tenant e
`public.{table}` para tabelas compartilhadas, respeitando o ContextVar
`table_case` para serviços MySQL legacy.

### Regra 5 — Consistência de migration ao mover de legacy para microserviço

Quando time porta serviço legacy para novo microserviço, verificações
abaixo são obrigatórias antes de escrever qualquer método de repository:

| Checagem | Como |
|----------|------|
| Nomes de coluna batem com plataforma 2.0 | Compare migration vs schema legacy |
| Todas as 8 colunas de auditoria presentes | Checklist §27 |
| Casing de identificador correto para o engine | Tabela §27 |
| Filtro `is_deleted` em todo read | `WHERE is_deleted = FALSE` |
| Schema é variável | `self._t()` em todas as queries |
| Sem aliases legacy | Sem `AS cod_tenant`, `AS dt_criacao`, etc. |
| Apenas placeholders posicionais | `$1, $2, ...` — nunca f-string com user data |

---

## 29. Convenções de migrations Alembic

Todas as migrations vivem em `alembic/versions/`. Escreva SQL puro com
`op.execute()` — sem types ou helpers DDL do SQLAlchemy.

### Dois tipos de migration — saiba qual está criando

| Tipo | Escopo | Aplicado com | Tabelas |
|------|--------|-------------|---------|
| **Compartilhada** | schema `public` (uma vez por serviço) | `alembic upgrade head` | `tenants`, `users`, `service_accounts`, tabelas de infra |
| **Tenant** | schema `tenant_{id}` (uma vez por tenant) | `alembic -x tenant_id=N upgrade head` | Tabelas de entidade de negócio (`items`, `orders`, `products`, …) |

**Regra prática:** se a tabela pertence a um módulo de domínio sob
`app/modules/`, é **migration de tenant**. Se é infra de plataforma, é
**migration compartilhada**.

### Criando migration para novo módulo (tabela de tenant)

```bash
alembic revision -m "create_{entity}_table"
# Edite o arquivo gerado — escreva SQL cru em upgrade() e downgrade()
```

Template para tabela de negócio tenant — **PostgreSQL** (identificadores lowercase):

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS {entities} (
            id          SERIAL PRIMARY KEY,
            -- colunas de domínio aqui (todas lowercase) --
            created_by  INTEGER,
            updated_by  INTEGER,
            created_at  TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            updated_at  TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            is_deleted  BOOLEAN   NOT NULL DEFAULT FALSE,
            is_active   BOOLEAN   NOT NULL DEFAULT TRUE,
            scope       VARCHAR(50)        DEFAULT '{entities}'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_{entities}_is_deleted ON {entities} (is_deleted)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS {entities}")
```

Template para tabela de negócio tenant — **MySQL** (tabela UPPERCASE, colunas lowercase):

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS `{ENTITIES}` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            -- colunas de domínio aqui (todas lowercase) --
            created_by  INT,
            updated_by  INT,
            created_at  TIMESTAMP NOT NULL DEFAULT UTC_TIMESTAMP(),
            updated_at  TIMESTAMP NOT NULL DEFAULT UTC_TIMESTAMP() ON UPDATE UTC_TIMESTAMP(),
            is_deleted  TINYINT(1) NOT NULL DEFAULT 0,
            is_active   TINYINT(1) NOT NULL DEFAULT 1,
            scope       VARCHAR(50)        DEFAULT '{ENTITIES}'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_{ENTITIES}_is_deleted ON `{ENTITIES}` (is_deleted)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `{ENTITIES}`")
```

> Placeholder do nome da tabela: `{entities}` para PostgreSQL, `{ENTITIES}`
> para MySQL. Nomes de coluna são sempre lowercase em ambos engines.

### Aplicando migrations

```bash
# Compartilhadas (schema public) — rode uma vez após deploy
alembic upgrade head

# Tenant único
alembic -x tenant_id=42 upgrade head

# Todos os tenants provisionados
python scripts/migrate_all_tenants.py

# Dry run (veja o que rodaria, sem executar)
python scripts/migrate_all_tenants.py --dry-run

# Rollback da última migration (schema public)
alembic downgrade -1

# Rollback para um tenant específico
alembic -x tenant_id=42 downgrade -1
```

### Regras
- NUNCA use `sa.Column()`, `sa.Integer()` ou qualquer type SQLAlchemy — escreva SQL cru.
- NUNCA use `op.create_table()` com colunas SQLAlchemy — use `op.execute("CREATE TABLE ...")`.
- SEMPRE inclua `IF NOT EXISTS` / `IF EXISTS` em upgrade/downgrade para idempotência.
- SEMPRE inclua todas as 8 colunas de auditoria (§27) em toda nova tabela de negócio.
- Nome de arquivo: `YYYYMMDD_{rev}_{slug}.py` (auto-gerado por `alembic revision -m`).

---

## 30. Criando um novo serviço

### Passo 1 — Clone e renomeie

```bash
cp -r platform-service-template {service-name}
cd {service-name}
# Substitui placeholder em todos os arquivos
grep -rl "service-name" . --include="*.py" --include="*.yml" --include="*.yaml" \
  --include="*.toml" --include="*.txt" --include="*.md" | \
  xargs sed -i 's/service-name/{service-name}/g'
```

### Passo 2 — Atualize config.py

Defina defaults específicos do serviço:
- `APP_NAME = "{service-name}"`
- `JWT_ISSUER = "{service-name}"`
- `JWT_AUDIENCE = "{service-name}-clients"`
- `KAFKA_CLIENT_ID = "{service-name}"`
- `KAFKA_CONSUMER_GROUP = "{service-name}"`
- `OTEL_SERVICE_NAME = "{service-name}"`
- `SERVICE_ID = "{service-name}"`
- `LOG_TEMP_FOLDER = "/tmp/{service-name}-logs"`

### Passo 3 — Remova módulo de exemplo

```bash
rm -rf app/modules/items/
# Remova migrations de items de alembic/versions/
```

### Passo 4 — Crie a lib pública em src/

Crie `src/platform_{service}/` com 4 arquivos (§20):
- `__init__.py` — exporta todos os tipos públicos
- `schemas.py` — modelos Pydantic públicos de resposta (auto-contido, sem app/)
- `events.py` — payloads tipados de eventos Kafka emitidos
- `client.py` — cliente HTTP herdando BaseAsyncClient

Depois torne importável dentro do próprio app/:
```bash
pip install -e .
```

### Passo 5 — Crie seus módulos (padrão de 7 arquivos por entidade)

Em `app/modules/{module}/schemas.py`, importe o schema público de src/:
```python
from platform_{service}.schemas import EntityResponse as EntityResponse  # noqa: F401
```

### Passo 6 — Crie migrations de banco

```bash
alembic revision -m "create_{entity}_table"
# Edite o arquivo gerado — escreva SQL cru em upgrade() e downgrade()
# Veja §29 para o template de migration
alembic upgrade head
```

### Passo 7 — Atualize .env.example e manifests k8s/

### Passo 8 — Adicione endpoint interno de migration (obrigatório se serviço tem tabelas de tenant)

Siga §45:
1. Crie `app/core/migrations.py` — runner Alembic async.
2. Crie `app/core/auth_deps.py` — dependency `require_internal_token`.
3. Crie `app/api/internal.py` — endpoint `POST /internal/migrate`.
4. Registre `internal_router` em `app/main.py` (fora de `api_router`).
5. Adicione `INTERNAL_API_TOKEN` em `config.py` e `.env.example`.
6. Adicione URL deste serviço em `PLATFORM_SERVICES` do `config.py` do platform-auth.

### Passo 9 — (Opcional) Adicione suporte a WebSocket

Se o serviço tem comunicação real-time com o frontend, siga §37.
Descomente `platform-ws-lib` em `requirements.txt`.

### Passo 10 — Rode checklist completo de validação (§33)

---

## 31. Migrando um serviço existente

### Passo 1 — Avalie o estado atual

```bash
# Encontre imports inline antigos no código de módulo
grep -rn "from app\.core\." app/modules/ app/main.py app/clients/ | \
  grep -v "from app\.core\.config\|from app\.core\.database\|from app\.core\.exceptions"

# Liste arquivos que não deveriam estar em app/core/
ls app/core/ | grep -v "__init__.py\|__pycache__\|config.py\|database.py\|exceptions.py\|limiter.py"

# Liste arquivos que não deveriam estar em app/events/
ls app/events/ | grep -v "__init__.py\|__pycache__\|scrubbers.py\|schemas.py"
```

### Passo 2 — Converta exceptions.py em wrapper fino

```python
"""Service exceptions — re-exporta de platform_core."""
from platform_core.exceptions import (  # noqa: F401
    AuthorizationError, ConflictError, DomainError, ErrorResponse,
    IntegrationClientError, NotFoundError, ValidationError,
    domain_exception_handler, generic_exception_handler, handle_domain_errors,
    http_exception_handler, integration_exception_handler, validation_exception_handler,
)
```

### Passo 3 — Atualize imports do main.py (substitua `app.core.*` por libs)

```
from app.core.logging import ...           →  from platform_core.logging import ...
from app.core.request_context import ...   →  from platform_core.request_context import ...
from app.core.limiter import ...           →  mantenha como app.core.limiter (crie se faltar, ver §22)
from app.core.security_headers import ...  →  from platform_observability.security_headers import ...
from app.core.tenant_middleware import ... →  from platform_tenant.middleware import ...
from app.observability.otel import ...     →  from platform_observability.otel import ...
from app.observability.sentry import ...   →  from platform_observability.sentry import ...
from app.events.bus_config import ...      →  from platform_events.bus_config import ...
from app.events.consumer import ...        →  from platform_events.consumer import ...
```

### Passo 4 — Atualize imports de módulo (sed em lote)

```bash
find app/modules app/clients -name "*.py" | xargs sed -i \
  -e 's/from app\.core\.base_repository import/from platform_core.base_repository import/g' \
  -e 's/from app\.core\.base_service import/from platform_core.base_service import/g' \
  -e 's/from app\.core\.base_client import/from platform_core.base_client import/g' \
  -e 's/from app\.core\.auth import/from platform_auth.jwt_manager import/g' \
  -e 's/from platform_observability\.limiter import limiter/from app.core.limiter import limiter/g' \
  -e 's/from app\.core\.constants import/from platform_core.constants import/g' \
  -e 's/from app\.core\.enums import/from platform_core.enums import/g' \
  -e 's/from app\.core\.request_context import/from platform_core.request_context import/g' \
  -e 's/from app\.core\.tz import/from platform_core.tz import/g' \
  -e 's/from app\.core\.i18n import/from platform_core.i18n import/g' \
  -e 's/from app\.core\.mappers import/from platform_core.mappers import/g' \
  -e 's/from app\.events\.decorators import/from platform_events.decorators import/g'
```

### Passo 5 — Apague arquivos de lib inline

```bash
# Apague de app/core/ (mantenha: config.py, database.py, exceptions.py, limiter.py)
rm -f app/core/auth.py app/core/base_client.py app/core/base_repository.py \
      app/core/base_service.py app/core/constants.py app/core/enums.py \
      app/core/i18n.py app/core/interfaces.py \
      app/core/mappers.py app/core/module_permissions.py app/core/platform.py \
      app/core/request_context.py app/core/security.py app/core/security_headers.py \
      app/core/tenant.py app/core/tenant_middleware.py app/core/tenant_provisioner.py \
      app/core/tz.py app/core/websocket.py
rm -rf app/core/logging/

# Apague de app/events/ (mantenha: __init__.py, scrubbers.py, schemas.py)
rm -f app/events/bus_config.py app/events/consumer.py \
      app/events/decorators.py app/events/kafka_event_bus.py

# Apague app/observability/ inteiro
rm -rf app/observability/
```

### Passo 5b — Crie/atualize app/core/limiter.py

Crie (ou sobrescreva com o padrão correto) o singleton do rate-limiter:
```python
"""Singleton de rate-limiter compartilhado entre main.py e todos os routers."""
from platform_observability.limiter import build_limiter
from app.core.config import settings

limiter = build_limiter(settings)
```

Depois atualize todo router de módulo que importa
`from platform_observability.limiter import limiter` para usar
`from app.core.limiter import limiter`.

### Passo 6 — Adicione settings de config faltantes

Garanta que `app/core/config.py` tem (use sintaxe nativa Python 3.12):
```python
RATE_LIMIT_STORAGE_URI: str | None = None
TRUSTED_PROXIES: list[str] = []
MAX_REQUEST_SIZE_BYTES: int = 1_048_576
```

### Passo 7 — Adicione dependências de lib em requirements.txt

Adicione o bloco do §42 deste documento.

### Passo 7b — Crie src/platform_{service}/ (se não existe)

Todo serviço deve ser também uma lib instalável. Crie os 4 arquivos (§20):
- `src/platform_{service}/__init__.py`
- `src/platform_{service}/schemas.py` — modelos públicos de resposta (sem `app/`)
- `src/platform_{service}/events.py` — payloads Kafka tipados
- `src/platform_{service}/client.py` — cliente HTTP

Atualize `pyproject.toml` para adicionar build-system e wheel target (§20).

Em cada `app/modules/{module}/schemas.py`, substitua a definição inline de
`{Entity}Response` por import do src/:
```python
from platform_{service}.schemas import EntityResponse as EntityResponse  # noqa: F401
```

Depois rode:
```bash
pip install -e .  # torna src/ importável dentro de app/
```

### Passo 8 — Verifique a stack de middlewares

Confirme que todos os 6 layers de middleware estão presentes e na ordem
correta (§22).

### Passo 9 — (Opcional) Migre infraestrutura WebSocket

Se o serviço tem `app/core/websocket.py` ou handler WS inline, migre para
`platform_ws`. Veja §37 para o padrão WSRouter.

### Passo 10 — Limpeza de type annotations Python 3.9 → 3.12

Rode o sed em lote do §40 para substituir `Optional[X]`, `List[X]`,
`Dict[X,Y]` por sintaxe nativa Python 3.12 (`X | None`, `list[X]`,
`dict[X,Y]`). Atualize arquivos de config (`pyproject.toml`, `Dockerfile`,
`ci.yml`) conforme §40.

### Passo 11 — Rode checklist de validação (§33)

---

## 32. Template de `config.py`

```python
"""Settings centralizadas e validadas."""
from __future__ import annotations
import logging, secrets
from functools import lru_cache
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=True,
    )
    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "{service-name}"
    APP_VERSION: str = "v1.0.0"
    ENVIRONMENT: str = "development"
    CORS_ALLOWED_ORIGINS: list[str] = Field(default=["http://localhost:3000"])
    DOCS_ENABLED: bool = True
    ROOT_PATH: str = "/{service-name}"

    # ── Database ──────────────────────────────────────────────────────────────
    DB_ENGINE: str = "postgresql"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "{service-name}"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_POOL_MIN_SIZE: int = 5
    DB_POOL_MAX_SIZE: int = 50
    DB_DSN: str | None = None

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 240
    JWT_ISSUER: str = "{service-name}"
    JWT_AUDIENCE: str = "{service-name}-clients"

    # ── Kafka ─────────────────────────────────────────────────────────────────
    KAFKA_ENABLED: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_SECURITY_PROTOCOL: str = "PLAINTEXT"
    KAFKA_SASL_MECHANISM: str | None = None
    KAFKA_SASL_USERNAME: str | None = None
    KAFKA_SASL_PASSWORD: str | None = None
    KAFKA_CLIENT_ID: str = "{service-name}"
    KAFKA_CONSUMER_ENABLED: bool = False
    KAFKA_CONSUMER_GROUP: str = "{service-name}"
    KAFKA_CONSUMER_STANDALONE: bool = False
    KAFKA_DLQ_ENABLED: bool = True

    # ── Observabilidade ───────────────────────────────────────────────────────
    OTEL_SERVICE_NAME: str = "{service-name}"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://tempo:4318"
    OTEL_TRACES_ENABLED: bool = False
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    LOG_LEVEL: str = "INFO"
    LOG_TEMP_FOLDER: str = "/tmp/{service-name}-logs"
    HASH_LOG: str | None = None

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_RPS: int = 50
    RATE_LIMIT_BURST: int = 100
    RATE_LIMIT_STORAGE_URI: str | None = None
    TRUSTED_PROXIES: list[str] = Field(default=[])
    MAX_REQUEST_SIZE_BYTES: int = 1_048_576

    # ── Identidade do serviço ─────────────────────────────────────────────────
    SERVICE_ID: str = "{service-name}"
    SERVICE_SECRET: str | None = None
    URL_AUTH: str = "http://platform-auth:8000/internal"
    INTERNAL_API_TOKEN: str = ""   # obrigatório para rotas /internal/* (§45)

    # ── Admin Database (MySQL produção — ADMIN_DB_* sobrescreve DB_* quando setado) ──
    ADMIN_DB_HOST: str | None = None
    ADMIN_DB_PORT: int = 3307
    ADMIN_DB_USER: str | None = None
    ADMIN_DB_PASSWORD: str | None = None

    # ── JWT estendido ─────────────────────────────────────────────────────────
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    JWT_JWKS_URL: str | None = None
    JWT_PRIVATE_KEY_PATH: str | None = None
    AUTH_DEV_BYPASS: bool = False

    # ── Kafka estendido ───────────────────────────────────────────────────────
    KAFKA_CONSUMER_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_CONSUMER_MAX_POLL_INTERVAL_MS: int = 300_000

    # ── Network / TLS ─────────────────────────────────────────────────────────
    NETWORK_TOPOLOGY: str = "docker"
    TLS_VERIFY: bool = True
    TLS_CLIENT_CERT: str | None = None
    TLS_CLIENT_KEY: str | None = None
    TLS_CA_BUNDLE: str | None = None

    # ── Multi-tenancy ─────────────────────────────────────────────────────────
    TENANT_JWT_CLAIM: str = "tenant_id"

    # ── Permissões ────────────────────────────────────────────────────────────
    SECURITY_ADVANCED_MODULES: str = ""
    PERMISSION_CACHE_TTL_SECONDS: int = 30
    URL_IAM: str = "http://platform-admin:8000/api/v1/iam"

    # ── Encryption de credenciais ─────────────────────────────────────────────
    CREDENTIAL_ENCRYPTION_KEY: str | None = None

    @field_validator("JWT_SECRET_KEY", mode="before")
    @classmethod
    def _generate_jwt_secret(cls, v: str) -> str:
        if not v:
            logger.warning("JWT_SECRET_KEY not set — generated ephemeral key.")
            return secrets.token_urlsafe(48)
        return v

    @model_validator(mode="after")
    def _build_dsn(self) -> "Settings":
        if self.DB_DSN is not None:
            return self
        host = self.ADMIN_DB_HOST or self.DB_HOST
        port = self.ADMIN_DB_PORT if self.ADMIN_DB_HOST else self.DB_PORT
        user = self.ADMIN_DB_USER or self.DB_USER
        password = self.ADMIN_DB_PASSWORD or self.DB_PASSWORD
        scheme = "postgresql" if self.DB_ENGINE == "postgresql" else "mysql"
        self.DB_DSN = f"{scheme}://{user}:{password}@{host}:{port}/{self.DB_NAME}"
        return self

    @model_validator(mode="after")
    def _block_insecure_production(self) -> "Settings":
        """Falha no startup se configuração insegura for detectada em production."""
        import os as _os
        if self.ENVIRONMENT != "production":
            return self
        if self.JWT_ALGORITHM.startswith("HS") and not _os.environ.get("JWT_SECRET_KEY"):
            raise ValueError("JWT_SECRET_KEY deve estar setado via variável de ambiente em produção.")
        if self.AUTH_DEV_BYPASS:
            raise ValueError("AUTH_DEV_BYPASS não pode estar habilitado em produção.")
        if "*" in self.CORS_ALLOWED_ORIGINS:
            raise ValueError("CORS_ALLOWED_ORIGINS não pode conter '*' em produção.")
        if self.NETWORK_TOPOLOGY == "cross-network" and not self.TLS_CLIENT_CERT:
            raise ValueError("TLS_CLIENT_CERT é obrigatório quando NETWORK_TOPOLOGY=cross-network.")
        return self

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

settings: Settings = get_settings()
```

---

## 33. Checklist de validação

Rode após toda operação de criar ou migrar. Todas as checagens devem passar.

### A. Auditoria de imports (deve devolver 0 linhas)

```bash
grep -rn "from app\.core\." app/modules/ app/main.py app/clients/ 2>/dev/null | \
  grep -v "from app\.core\.config\|from app\.core\.database\|from app\.core\.exceptions"

grep -rn "from app\.events\." app/modules/ app/main.py app/clients/ 2>/dev/null
grep -rn "from app\.observability\." app/ --include="*.py" 2>/dev/null
```

### B. Auditoria de diretório core (não deve ter arquivos extras)

```bash
ls app/core/ | grep -v "__init__.py\|__pycache__\|config.py\|database.py\|exceptions.py\|limiter.py"
```

### C. Auditoria de diretório events (não deve ter arquivos extras)

```bash
ls app/events/ | grep -v "__init__.py\|__pycache__\|scrubbers.py\|schemas.py"
```

### D. Campos obrigatórios de config

```bash
python -c "
from app.core.config import settings
required = ['APP_NAME','ENVIRONMENT','DB_ENGINE','JWT_ALGORITHM','KAFKA_ENABLED',
            'OTEL_TRACES_ENABLED','LOG_LEVEL','RATE_LIMIT_RPS','RATE_LIMIT_BURST',
            'RATE_LIMIT_STORAGE_URI','TRUSTED_PROXIES','MAX_REQUEST_SIZE_BYTES']
missing = [f for f in required if not hasattr(settings, f)]
print('MISSING:', missing) if missing else print('OK: all required settings present')
"
```

### E. Stack de middleware (deve imprimir 4)

```bash
grep -c "RequestSizeLimitMiddleware\|SecurityHeadersMiddleware\|SlowAPIMiddleware\|RequestLoggingMiddleware" app/main.py
```

### F. Dependências de lib (deve imprimir pelo menos 4)

```bash
grep "platform-core-lib\|platform-auth-lib\|platform-events-lib\|platform-observability-lib" requirements.txt | grep -v "^#" | wc -l
```

### G. Estrutura de módulo

```bash
python scripts/validate_module_structure.py
```

### H. Testes passam

```bash
pytest tests/ -x --tb=short
```

### I. Sem arquivos antigos em app/core/

```bash
ls app/core/ app/events/
# app/core/: __init__.py config.py database.py exceptions.py limiter.py
# app/events/: __init__.py scrubbers.py (schemas.py opcional)
```

### J. Lib pública é auto-contida (deve devolver 0 linhas)

```bash
grep -rn "from app\." src/ 2>/dev/null
```

### K. README.md existe e cobre as seções obrigatórias

```bash
grep -l "Overview\|Public Library\|Kafka Events\|Local Development\|Configuration" README.md \
  && echo "OK" || echo "MISSING SECTIONS in README.md"
```

### L. API_CONTRACT.md existe e cobre as seções obrigatórias

```bash
grep -l "Autenticação\|Formato de resposta\|Paginação\|Erros\|Endpoints REST\|Changelog" API_CONTRACT.md \
  && echo "OK" || echo "MISSING SECTIONS in API_CONTRACT.md"
```

### L2. Sem queries com schema hardcoded ou faltando schema variable (deve devolver 0 linhas)

```bash
# Schema names hardcoded
grep -rn "tenant_[0-9]\+\." app/modules/ --include="*.py"
# Tabela bare sem self._t() em arquivos de repository
grep -n "execute\|fetch_one\|fetch_all\|fetchval" app/modules/*/repository.py \
  | grep -v "_t()" | grep -v "public\." | grep -v "information_schema" \
  && echo "WARNING: queries may be missing schema variable" || echo "OK"
```

### M. Schema OpenAPI é válido e completo

```bash
# Inicie o serviço primeiro: uvicorn app.main:app --port 8000

# Schema carrega sem erros
curl -sf http://localhost:8000/{service-name}/openapi.json | python -m json.tool > /dev/null \
  && echo "OK: schema valid" || echo "ERROR: schema invalid"

# Toda rota tem summary e operationId
curl -s http://localhost:8000/{service-name}/openapi.json | python -c "
import json, sys
schema = json.load(sys.stdin)
issues = []
for path, methods in schema.get('paths', {}).items():
    for method, op in methods.items():
        if method == 'parameters': continue
        if not op.get('summary'): issues.append(f'Missing summary: {method.upper()} {path}')
        if not op.get('operationId'): issues.append(f'Missing operationId: {method.upper()} {path}')
print('\n'.join(issues) if issues else 'OK: all routes documented')
sys.exit(1 if issues else 0)
"

# Bearer security scheme presente
curl -s http://localhost:8000/{service-name}/openapi.json | python -c "
import json, sys
s = json.load(sys.stdin)
ok = 'BearerAuth' in s.get('components', {}).get('securitySchemes', {})
print('OK: BearerAuth present' if ok else 'ERROR: BearerAuth missing')
sys.exit(0 if ok else 1)
"
```

### N. Todo router v1 tem autenticação (deve imprimir OK)

```bash
# Routers sem dependency jwt_manager
grep -rn "APIRouter" app/modules/ --include="*.py" \
  | grep -v "jwt_manager\|health\|__pycache__" \
  && echo "WARNING: check routers for missing jwt_manager dependency" || echo "OK"
```

### O. Casing de identificador consistente com o engine de DB (revisão manual)

```bash
# PostgreSQL: nomes de tabela devem ser lowercase — flag UPPERCASE em migrations
grep -rn "CREATE TABLE.*[A-Z]" alembic/versions/ --include="*.py" \
  | grep -v "SERIAL\|INTEGER\|VARCHAR\|BOOLEAN\|TIMESTAMP\|PRIMARY\|DEFAULT\|NOT NULL\|IF NOT\|AUTO_INC\|TINYINT\|BIGINT\|TEXT\|INDEX\|CASCADE\|UTC" \
  && echo "WARNING: check for UPPERCASE table names in PostgreSQL migrations" || echo "OK (PostgreSQL)"

# MySQL: nomes de tabela devem ser UPPERCASE — flag lowercase em migrations
# (revise manualmente — depende se o serviço é MySQL ou PostgreSQL)
```

### P. Endpoint interno de migration presente (se serviço tem tabelas tenant)

```bash
grep -rn "internal/migrate\|run_tenant_migration" app/ --include="*.py" \
  && echo "OK: migration endpoint found" || echo "MISSING: add app/api/internal.py (§45)"
```

---

## 34. Requisitos de teste

**Cobertura mínima: 70%** (enforçado em CI via `--cov-fail-under=70`)

### Testes unitários devem cobrir
- Todo método de service: happy path + NotFoundError + ValidationError
- Todo método de repository (mock do DatabasePool)
- Validação de schema Pydantic (payloads válidos + inválidos)
- Mapper functions (row dict para response schema)

### Testes de integração devem cobrir
- CRUD completo via AsyncClient com DB real
- Execução de handler Kafka (mock do bus, service layer real)
- `/health/live` retorna 200
- `/health/ready` retorna 200 quando DB está up, 503 quando down

### Rodar testes
```bash
pytest tests/ -v --cov=app --cov-fail-under=70 --cov-report=term-missing
```

---

## 35. Auditoria de segurança

### Prevenção de SQL injection
- [ ] `_UPDATABLE_COLUMNS` frozenset definido em todo repository
- [ ] Sem f-string SQL com dados de usuário
- [ ] Toda cláusula WHERE usa parâmetros posicionais `$1, $2, ...`
- [ ] Nomes de tabela usam helper `self._t()` (previne injection de schema tenant)

### Autenticação
- [ ] **Sem rotas públicas** — todo `APIRouter` sob `app/api/v1/` tem
      `dependencies=[Depends(jwt_manager)]`
- [ ] As ÚNICAS rotas isentas de auth são `/health/live` e `/health/ready`
      (definidas em `app/api/health.py`)
- [ ] Em `platform-auth` — endpoints internos de access-definition usam
      `INTERNAL_API_TOKEN` do `.env` (ver §44)
- [ ] `AUTH_DEV_BYPASS = False` em produção (ENVIRONMENT=production bloqueia via validator)
- [ ] `JWT_SECRET_KEY` vem de variável de ambiente — nunca hardcoded
- [ ] Algoritmo JWT em `{"HS256", "HS384", "HS512", "RS256"}`

### Rate limiting
- [ ] Todo endpoint de escrita tem decorator `@limiter.limit()`
- [ ] `app.state.limiter = limiter` setado em main.py antes dos middlewares

### Tamanho de request
- [ ] `MAX_REQUEST_SIZE_BYTES` setado em config
- [ ] `RequestSizeLimitMiddleware` registrado como middleware mais externo

### CORS
- [ ] `CORS_ALLOWED_ORIGINS` não contém `"*"` em produção

### Scan de CVE
```bash
pip-audit
```

### Container
- [ ] Usuário não-root em Dockerfile (uid 1000)
- [ ] `readOnlyRootFilesystem: true` no securityContext do K8s deployment
- [ ] Secrets em `k8s/secret.yaml`, não em `k8s/configmap.yaml`

---

## 36. Convenções de eventos Kafka

### Nome de tópico: `{domain}.{action}` (snake_case)
```
items.created    items.updated    items.deleted
auth.user_created   auth.user_deleted
connector.synced    connector.failed
```

### Payload padrão de evento
```python
{
    "event_id": "uuid4-string",
    "occurred_at": "2026-01-01T00:00:00Z",  # UTC ISO 8601
    "tenant_id": "tenant_123",
    "service_id": "service-name",
    "user_id": 42,
    "request_id": "uuid4-string",
    "data": { ... }
}
```

### Regras de handler
- Handlers DEVEM ser idempotentes (Kafka entrega at-least-once)
- Handlers DEVEM logar `topic`, identificadores-chave e desfecho
- Handlers cross-module usam `group_id` único:
  ```python
  @handle_event(topic="auth.user_deleted", group_id="{service-name}-cleanup")
  ```
- DLQ habilitado por padrão (`KAFKA_DLQ_ENABLED=True`): mensagens que falham
  vão para `{topic}.dlq`

---

## 37. Padrão WebSocket

Apenas adicione infra WebSocket se o serviço comunica dados real-time ao
frontend. Requer: `platform-ws-lib` em `requirements.txt`.

### Arquivo de módulo: `app/modules/{module}/routers_ws.py`

```python
from platform_ws import WSRouter, ws_broadcast, ws_push_to_user

ws_router = WSRouter(prefix="{module}")

# Canal broadcast — todos os usuários conectados recebem eventos
async def emit_{module}_created(entity_id: int, origin_user_id: str) -> None:
    await ws_broadcast("{module}", "{module}.created", {"id": entity_id}, origin_user_id)

# Receive-only (server faz push, client não envia nada)
@ws_router.channel()
async def {module}_events(message: dict, session_id: str, jwt_claims: dict) -> None:
    pass

WS_ROUTERS = [ws_router]
```

### Export em `app/modules/{module}/__init__.py`
```python
from app.modules.{module}.routers_ws import WS_ROUTERS as _WS_ROUTERS
WS_ROUTERS = _WS_ROUTERS
```

### Registro em `app/main.py` (após `app.include_router(api_router)`)
```python
import app.modules as _modules
from platform_ws import register_ws_routers
register_ws_routers(app, _modules)
```

### Graceful shutdown no lifespan
```python
from platform_ws import connection_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await connection_manager.close_all()
    await close_pool()
```

### Convenção de session ID
- Canal raiz:    `{prefix}:{user_sub}`        ex.: `domains:42`
- Canal nomeado: `{prefix}/{name}:{user_sub}` ex.: `domains/team:42`

### Dois tipos de canal
- **Broadcast** (`ws_broadcast`): todos conectados recebem o evento (domains, agents, etc.)
- **Pessoal** (`ws_push_to_user`): apenas um usuário específico recebe (notificações, fila)

### Formato de mensagem (BaseEvent)
```json
{
    "type": "entity.action",
    "payload": { ... },
    "originUserId": "42",
    "timestamp": "2026-01-01T00:00:00Z"
}
```

### requirements.txt — descomente ao adicionar WebSocket
```
platform-ws-lib @ git+ssh://git@github.com/dataforalltech/platform-ws-lib.git@v0.1.0
```

---

## 38. Contrato de health check

### `GET /health/live` — liveness
- Devolve `{"status": "ok"}` (200) se o processo está vivo
- K8s `livenessProbe`: initialDelaySeconds=10, periodSeconds=15
- Deve responder em < 500ms

### `GET /health/ready` — readiness
- Devolve `{"status": "ok", "database": "ok"}` (200) quando pronto
- Devolve `{"status": "not_ready", "database": "error"}` (503) em falha
- K8s `readinessProbe`: initialDelaySeconds=15, periodSeconds=10

---

## 39. Anti-patterns

```python
# ERRADO: lógica de negócio em routers
@router.post("/items")
async def create_item(data: ItemCreate, pool = Depends(get_pool)):
    await pool.execute("INSERT INTO items ...", data.name)  # use service layer

# ERRADO: hard delete
await pool.execute("DELETE FROM items WHERE id = $1", item_id)  # use is_deleted = TRUE

# ERRADO: SQL inline em services
class ItemService:
    async def create(self, data): await self.pool.execute("INSERT ...")  # use repository

# ERRADO: duplicar código de lib no serviço
# Copiar auth.py / base_repository.py para app/core/ — NUNCA

# ERRADO: engolir exceção
try:
    result = await service.create(data)
except Exception:
    pass  # no mínimo: logue a exceção

# ERRADO: I/O bloqueante em async
import time; time.sleep(1)  # use: await asyncio.sleep(1)

# ERRADO: CORS com wildcard em produção
CORS_ALLOWED_ORIGINS: List[str] = ["*"]

# ERRADO: f-string SQL com input do usuário
table = request.query_params.get("table")
await pool.execute(f"SELECT * FROM {table}")  # SQL injection

# ERRADO: schema hardcoded em query (§28 — schema deve sempre ser variável)
await pool.execute("SELECT * FROM tenant_42.items WHERE id = $1", item_id)

# ERRADO: nome de tabela sem schema resolver (schema deve sempre ser variável)
await pool.execute("SELECT * FROM items WHERE id = $1", item_id)
# use: f"SELECT * FROM {self._t()} WHERE id = $1"

# ERRADO: query em coluna que não existe na migration (§28)
await pool.execute("SELECT cod_tenant FROM items WHERE id = $1", item_id)
# sempre verifique nomes de coluna contra alembic/versions/ antes de escrever queries

# ERRADO: tabela MySQL com nome lowercase (§27 — MySQL tables UPPERCASE)
CREATE TABLE IF NOT EXISTS `items` (...)    -- MySQL
# correto: CREATE TABLE IF NOT EXISTS `ITEMS` (...)

# ERRADO: tabela PostgreSQL com nome UPPERCASE (§27 — PostgreSQL identifiers lowercase)
CREATE TABLE IF NOT EXISTS "ITEMS" (...)    -- PostgreSQL
# correto: CREATE TABLE IF NOT EXISTS items (...)

# ERRADO: nome de coluna em UPPERCASE em qualquer engine (colunas sempre lowercase)
CREATE TABLE items (ID INT, Name VARCHAR(255), CreatedBy INT)
# correto: CREATE TABLE items (id INT, name VARCHAR(255), created_by INT)

# ERRADO: router sem dependency jwt_manager — cria rota pública (§44)
router = APIRouter(prefix="/items", tags=["Items"])
# Todo router DEVE ter: dependencies=[Depends(jwt_manager)]

# ERRADO: rota individual sem auth ao invés de dependency router-level
@router.get("/items")
async def list_items():  # sem checagem de auth — rota pública
    ...
# use router-level: APIRouter(..., dependencies=[Depends(jwt_manager)])

# ERRADO: modificar lib privada sem aprovação do owner (§18)
# editar qualquer arquivo dentro de platform-core-lib, platform-auth-lib, etc.
# → PARE e abra LIB CHANGE REQUEST; aguarde aprovação de @caiog
```

---

## 40. Migração Python 3.9 → 3.12

Rode estes passos sempre que migrar serviço existente de Python 3.9/3.10/3.11
para 3.12.

### Passo 1 — Arquivos de config (4 arquivos)

**`pyproject.toml`** — 3 campos:
```toml
[project]
requires-python = ">=3.12"

[tool.black]
target-version = ['py312']

[tool.ruff]
target-version = "py312"

[tool.mypy]
python_version = "3.12"
```

**`Dockerfile`** — ambos os stages builder e runtime:
```dockerfile
FROM python:3.12-slim AS builder
FROM python:3.12-slim AS runtime
```

**`.github/workflows/ci.yml`** — todas as entradas `python-version`:
```yaml
python-version: "3.12"
```

**`docker-compose.yml`** — se declara imagem Python diretamente:
```yaml
image: python:3.12-slim
```

### Passo 2 — Type annotations (sed em lote)

Python 3.10+ suporta sintaxe nativa de union. Rode da raiz do serviço:

```bash
# Remova imports deprecated de typing e substitua por sintaxe nativa
find app -name "*.py" | xargs sed -i \
  -e 's/Optional\[int\]/int | None/g' \
  -e 's/Optional\[str\]/str | None/g' \
  -e 's/Optional\[float\]/float | None/g' \
  -e 's/Optional\[bool\]/bool | None/g' \
  -e 's/Optional\[dict\]/dict | None/g' \
  -e 's/Optional\[list\]/list | None/g' \
  -e 's/Optional\[Any\]/Any | None/g' \
  -e 's/Dict\[/dict[/g' \
  -e 's/List\[/list[/g' \
  -e 's/Tuple\[/tuple[/g' \
  -e 's/Set\[/set[/g' \
  -e 's/FrozenSet\[/frozenset[/g'

# Após o sed: limpe imports de typing agora não usados
# Remova linhas que apenas importam List, Dict, Optional, Tuple (mas mantenha Any, ClassVar, etc.)
# Revise manualmente: grep -rn "from typing import" app/ --include="*.py"
```

> **Mantenha de `typing`:** `Any`, `ClassVar`, `TypeVar`, `Generic`, `Protocol`,
> `runtime_checkable`, `overload`, `TYPE_CHECKING`, `cast`, `Union` (quando
> precisar para compat), `Callable`, `Iterator`, `Generator`, `AsyncGenerator`,
> `AsyncIterator`

### Passo 3 — Deprecations do asyncio

```bash
# get_event_loop() deprecated em 3.10, removido em 3.12 — substitua por get_running_loop()
grep -rn "get_event_loop()" app/ --include="*.py"
# Substitua cada ocorrência:
# asyncio.get_event_loop() → asyncio.get_running_loop()
# (apenas seguro dentro de contexto async; use asyncio.new_event_loop() em outro lugar)
```

### Passo 4 — Remova `from __future__ import annotations` (opcional)

Em Python 3.12, PEP 563 (postponed evaluation) é o default na maior parte
dos casos. `from __future__ import annotations` continua válido — você pode
mantê-lo para forward references. Apenas remova se causar problemas com
validators Pydantic v2.

### Passo 5 — Valide

```bash
# Confirme versão Python
python --version  # deve ser 3.12.x

# Rode linters — agora aplicam regras de 3.12
ruff check app/
mypy app/ --ignore-missing-imports

# Rode testes
pytest tests/ -x --tb=short
```

### Quebras comuns 3.9 → 3.12 a observar

| Issue | Fix |
|-------|-----|
| `asyncio.get_event_loop()` em contexto sync | Use `asyncio.new_event_loop()` ou reestruture |
| Decorator `asyncio.coroutine` | Removido em 3.11 — use `async def` |
| `distutils` | Removido em 3.12 — use `packaging` ou `setuptools` |
| `typing.Pattern` | Removido em 3.12 — use `re.Pattern` |
| `typing.Match` | Removido em 3.12 — use `re.Match` |
| Validators Pydantic v1 | Migrar para Pydantic v2 (`@field_validator`) |

---

## 41. Checklist de novo módulo

- [ ] `__init__.py` exporta `V1_ROUTERS` e `EVENT_HANDLERS`
- [ ] `schemas.py` tem `{Entity}Create`, `{Entity}Update`, `{Entity}Response(AuditFieldsMixin)`
- [ ] `repository.py` herda `platform_core.base_repository.BaseRepository`
- [ ] `repository.py` define `TABLE` (str) e `_UPDATABLE_COLUMNS` (frozenset)
- [ ] `repository.py` usa placeholders `$1, $2, ...` em todo lugar
- [ ] `repository.py` filtra `WHERE is_deleted = FALSE` em todos os reads
- [ ] `services.py` herda `platform_core.base_service.BaseService`
- [ ] `services.py` chama `self._validate_id()`, `self._log_operation()`, `self._ensure_found()`
- [ ] `routers.py` tem função factory DI `_get_service()`
- [ ] `routers.py` todo endpoint de escrita tem decorator `@limiter.limit()`
- [ ] `handlers.py` todo handler é idempotente e loga topic + identificadores
- [ ] `handlers.py` exporta `EVENT_HANDLERS = [...]`
- [ ] Migration criada em `alembic/versions/` com colunas de auditoria
- [ ] `{Entity}Response` definido em `src/platform_{service}/schemas.py` e re-exportado
      em `app/modules/{module}/schemas.py`
- [ ] Payload Kafka tipado para cada evento emitido adicionado em `src/platform_{service}/events.py`
- [ ] Novo endpoint HTTP coberto em `src/platform_{service}/client.py`
- [ ] `src/platform_{service}/__init__.py` atualizado com novos exports públicos
- [ ] Testes unitários adicionados em `tests/unit/test_{module}.py`
- [ ] Testes de integração adicionados em `tests/integration/test_{module}.py`
- [ ] Tabelas do `README.md` atualizadas (API, Kafka Events, Modules)
- [ ] `API_CONTRACT.md` atualizado: novos endpoints na §6, novos WS events na §7,
      entrada de changelog na §9
- [ ] Todo novo endpoint tem `summary`, `description`, `responses` e `operation_id` (§24)
- [ ] Todo novo `Field()` tem `description`; todo schema novo tem `json_schema_extra` com `example`
- [ ] Checagem M de OpenAPI passa (schema válido, todas as rotas documentadas, BearerAuth presente)

---

## 42. Bloco de dependências para `requirements.txt`

```
# Bibliotecas privadas da plataforma
# SSH (dev local):
platform-core-lib @ git+ssh://git@github.com/dataforalltech/platform-core-lib.git@v0.1.0
platform-database-lib @ git+ssh://git@github.com/dataforalltech/platform-database-lib.git@v0.1.0
platform-auth-lib @ git+ssh://git@github.com/dataforalltech/platform-auth-lib.git@v0.1.0
platform-events-lib @ git+ssh://git@github.com/dataforalltech/platform-events-lib.git@v0.1.0
platform-observability-lib @ git+ssh://git@github.com/dataforalltech/platform-observability-lib.git@v0.1.0
platform-tenant-lib @ git+ssh://git@github.com/dataforalltech/platform-tenant-lib.git@v0.1.0
platform-files-lib @ git+ssh://git@github.com/dataforalltech/platform-files-lib.git@v0.1.0
platform-log-lib @ git+ssh://git@github.com/dataforalltech/platform-log-lib.git@v0.1.0
platform-data-types-lib @ git+ssh://git@github.com/dataforalltech/platform-data-types-lib.git@v0.1.0
# platform-ws-lib @ git+ssh://git@github.com/dataforalltech/platform-ws-lib.git@v0.1.0  # descomente se serviço usa WebSockets
# HTTPS / CI-CD (set GITHUB_TOKEN):
# platform-core-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-core-lib.git@v0.1.0
# platform-database-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-database-lib.git@v0.1.0
# platform-auth-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-auth-lib.git@v0.1.0
# platform-events-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-events-lib.git@v0.1.0
# platform-observability-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-observability-lib.git@v0.1.0
# platform-tenant-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-tenant-lib.git@v0.1.0
# platform-files-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-files-lib.git@v0.1.0
# platform-log-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-log-lib.git@v0.1.0
# platform-data-types-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-data-types-lib.git@v0.1.0
# platform-ws-lib @ git+https://${GITHUB_TOKEN}@github.com/dataforalltech/platform-ws-lib.git@v0.1.0  # descomente se serviço usa WebSockets
```

---

## 43. Requisitos de CI/CD

### `ci.yml` — jobs obrigatórios

| Job | Tools | Bloqueia deploy? |
|-----|-------|------------------|
| `lint` | ruff, mypy, black, validate_module_structure.py | sim |
| `security` | pip-audit (CVE scan) | sim |
| `api-contract` | oasdiff (drift de schema OpenAPI) | apenas warn |
| `test` | pytest + PostgreSQL real + Redis real, 70% coverage | sim |

`deploy.yml` dispara automaticamente após `ci.yml` passar em `main`.

### Autenticação para libs privadas em CI

As libs da plataforma usam `git+ssh://` em `requirements.txt` (dev local).
CI reescreve essas URLs para HTTPS automaticamente usando `GITHUB_TOKEN`:

```yaml
- name: Configure git for private platform libs
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "git+ssh://git@github.com/"

- run: pip install -r requirements.txt
```

`GITHUB_TOKEN` é fornecido automaticamente pelo GitHub Actions — sem secret
manual, desde que o workflow tenha permissão `contents: read` e o runner
tenha acesso aos repos da org `dataforalltech` (requer PAT da org ou GitHub
App se cross-org).

### Secrets e variáveis no GitHub do repo

Configure em **Settings → Secrets and variables → Actions** de cada repo de serviço:

#### Secrets (`secrets.*`)
| Nome | Valor |
|------|-------|
| `REGISTRY_USER` | username do registry Docker |
| `REGISTRY_PASSWORD` | password ou token do registry Docker |
| `KUBECONFIG` | kubeconfig base64-encoded do cluster alvo |
| `CODECOV_TOKEN` | token de upload do Codecov (opcional) |
| `SLACK_WEBHOOK` | webhook do Slack para alertas de falha de deploy (opcional) |

#### Variables (`vars.*`)
| Nome | Exemplo |
|------|---------|
| `REGISTRY_URL` | `d4all.azurecr.io/dataforall/3.0` |
| `IMAGE_NAME` | `platform-analytics` |
| `K8S_NAMESPACE` | `platform` |
| `K8S_DEPLOYMENT_NAME` | `platform-analytics` |

### `deploy.yml` — fluxo

```
CI passa em main
    → build Docker
    → push para Azure Container Registry (d4all.azurecr.io/dataforall/3.0/{IMAGE_NAME}:{tag})
    → Portainer webhook (dispara redeploy do stack alvo)
    → deploy: kubectl set image → rollout status (timeout 300s)
              → health check (readyReplicas > 0)
              → rollback automático em falha
```

**Formato de tag:** `v3.{YYYYMMDD}-{sha7}` (ex.: `v3.20260505-8f62c32`).
Esse formato permite ordenação cronológica + rastreabilidade ao commit exato.

Re-deploy manual: **Actions → Deploy → Run workflow** (escolha o ambiente).

### Procedimento de rollback

```bash
# Liste tags de imagem recentes
kubectl rollout history deployment/{service-name} -n platform

# Rollback para revision anterior
kubectl rollout undo deployment/{service-name} -n platform

# Rollback para revision específica
kubectl rollout undo deployment/{service-name} -n platform --to-revision=N
```

---

## 44. Política de autenticação (sem rotas públicas)

### Regra: todo endpoint exige Bearer token

**Nenhuma rota pode ser publicamente acessível.** Todos os endpoints sob
`/api/v1/` DEVEM exigir JWT válido. As únicas exceções são as health probes
do Kubernetes.

| Path | Auth obrigatória? | Motivo |
|------|-------------------|--------|
| `/api/v1/**` | SIM — sempre | Dados de negócio, escopados ao tenant |
| `/health/live` | NÃO | Liveness probe Kubernetes |
| `/health/ready` | NÃO | Readiness probe Kubernetes |

### Como aplicar — dependency router-level (padrão obrigatório)

Aplique `jwt_manager` como dependency **router-level** para que cubra todas
as rotas do router automaticamente. Nunca dependa de auth por endpoint —
é fácil esquecer.

```python
from platform_auth.jwt_manager import jwt_manager
from fastapi import APIRouter, Depends

# CORRETO — todas as rotas deste router exigem Bearer token válido
router = APIRouter(
    prefix="/items",
    tags=["Items"],
    dependencies=[Depends(jwt_manager)],
)

@router.get("")          # protegido — jwt_manager roda automaticamente
async def list_items(): ...

@router.post("")         # protegido — jwt_manager roda automaticamente
async def create_item(): ...
```

### Aggregator de v1 router — aplique também no topo

Em `app/api/v1/__init__.py`, o `v1_router` que agrega todos os routers de
módulo deve também carregar a dependency como rede de segurança:

```python
from platform_auth.jwt_manager import jwt_manager
from fastapi import APIRouter, Depends

v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(jwt_manager)])

# Routers de módulo são incluídos aqui — eles herdam a dependency
for router in V1_ROUTERS:
    v1_router.include_router(router)
```

### platform-auth — endpoints internos de access-definition

`platform-auth` contém endpoints usados por processos backend para definir
permissões, criar tenants e gerenciar usuários. Esses **não** são chamados
pelo frontend e nunca devem ser publicamente acessíveis pela internet.

Esses endpoints usam um **token interno de API** estático armazenado em `.env`:

```env
# .env
INTERNAL_API_TOKEN=<segredo-longo-aleatório>   # usado apenas por processos backend
```

#### Dependency para rotas internas

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from app.core.config import settings

_internal_key_header = APIKeyHeader(name="X-Internal-Token", auto_error=False)

def require_internal_token(key: str | None = Security(_internal_key_header)) -> None:
    """Gate para endpoints chamados apenas por processos backend confiáveis."""
    if not key or key != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=403, detail="Internal token required.")
```

#### Uso em routers do platform-auth

```python
from app.core.auth_deps import require_internal_token

# Router interno — nunca exposto à internet pública
internal_router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_internal_token)],
)

@internal_router.post("/provision-tenant")
async def provision_tenant_endpoint(body: ProvisionRequest): ...

@internal_router.post("/assign-role")
async def assign_role(body: AssignRoleRequest): ...
```

#### Adição ao `.env.example` (obrigatório no platform-auth)

```env
# Token backend-to-backend interno — NUNCA expor em frontend ou APIs públicas
INTERNAL_API_TOKEN=changeme_replace_with_64_char_random_secret
```

#### Adição ao `config.py` (obrigatório no platform-auth)

```python
INTERNAL_API_TOKEN: str = Field(
    ...,
    description="Token estático para chamadas backend-to-backend internas. Deve estar em .env.",
)
```

---

## 45. Endpoint interno de migração de tenant

Todo serviço que tem tabelas tenant-scoped DEVE expor endpoint interno que
roda suas próprias migrations Alembic para um dado `tenant_id`. Isso permite
que `platform-auth` provisione um novo cliente automaticamente em toda a
plataforma chamando cada serviço após criar o registro de tenant.

---

### 45.1 — O helper de migration

Crie `app/core/migrations.py` em todo serviço que tem migrations de tenant:

```python
"""Runner programático de Alembic para provisionamento de tenant."""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def run_tenant_migration(tenant_id: str, alembic_ini: str = "alembic.ini") -> dict:
    """Roda ``alembic -x tenant_id={tenant_id} upgrade head`` para um único tenant.

    Executa Alembic como subprocess para herdar o working directory e ambiente
    corretos — idêntico a rodar o comando CLI manualmente.

    Args:
        tenant_id: PostgreSQL: UUID string. MySQL: nome do database (ex.: PLATFORM_DEV).
        alembic_ini: Path para alembic.ini (default: raiz do projeto).

    Returns:
        {"success": bool, "output": str, "error": str}
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "alembic", "-x", f"tenant_id={tenant_id}", "upgrade", "head",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )
        stdout, stderr = await proc.communicate()
        success = proc.returncode == 0
        if success:
            logger.info("Tenant migration OK | tenant_id=%s", tenant_id)
        else:
            logger.error(
                "Tenant migration FAILED | tenant_id=%s | stderr=%s",
                tenant_id, stderr.decode(),
            )
        return {
            "success": success,
            "output": stdout.decode(),
            "error": stderr.decode(),
        }
    except Exception as exc:
        logger.exception("Tenant migration error | tenant_id=%s", tenant_id)
        return {"success": False, "output": "", "error": str(exc)}
```

---

### 45.2 — O endpoint interno de migration

Adicione o router abaixo em todo serviço que tem migrations de tenant.
Crie `app/api/internal.py`:

```python
"""Endpoints internos — chamáveis apenas por processos backend confiáveis."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth_deps import require_internal_token
from app.core.migrations import run_tenant_migration

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_internal_token)],
    include_in_schema=False,   # esconde do Swagger UI público
)


class MigrateRequest(BaseModel):
    tenant_id: str


class MigrateResponse(BaseModel):
    tenant_id: str
    success: bool
    output: str
    error: str
    ran_at: str


@router.post(
    "/migrate",
    response_model=MigrateResponse,
    summary="Run Alembic migrations for a tenant",
)
async def migrate_tenant(body: MigrateRequest) -> MigrateResponse:
    """Roda ``alembic upgrade head`` para o tenant_id dado.

    Chamado por platform-auth após provisionar novo tenant para garantir que
    as tabelas deste serviço existam no schema/database do tenant.
    """
    result = await run_tenant_migration(body.tenant_id)
    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "MIGRATION_FAILED",
                "message": f"Alembic migration failed for tenant {body.tenant_id!r}",
                "detail": result["error"],
            },
        )
    return MigrateResponse(
        tenant_id=body.tenant_id,
        success=True,
        output=result["output"],
        error="",
        ran_at=datetime.now(timezone.utc).isoformat(),
    )
```

Registre este router em `app/main.py` (fora de `api_router`, sem prefixo `/api/v1`):

```python
from app.api.internal import router as internal_router
app.include_router(internal_router)
```

---

### 45.3 — `app/core/auth_deps.py` (compartilhado entre serviços)

Cada serviço precisa da dependency de token interno. Crie `app/core/auth_deps.py`:

```python
"""Dependencies de autenticação compartilhadas entre routers."""
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import settings

_internal_key_header = APIKeyHeader(name="X-Internal-Token", auto_error=False)


def require_internal_token(key: str | None = Security(_internal_key_header)) -> None:
    """Exige header X-Internal-Token igual ao INTERNAL_API_TOKEN do .env."""
    if not key or key != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status_code=403, detail="Internal token required.")
```

Adicione em `app/core/config.py`:
```python
INTERNAL_API_TOKEN: str = ""   # deve estar em .env para que rotas /internal/* funcionem
```

Adicione em `.env.example`:
```env
INTERNAL_API_TOKEN=changeme_replace_with_64_char_random_secret
```

---

### 45.4 — Orquestração no platform-auth (fluxo de provisionamento de novo tenant)

Quando `platform-auth` cria novo tenant, ele deve:
1. Inserir o registro do tenant em `public.tenants`.
2. Rodar suas próprias migrations Alembic (`alembic -x tenant_id=X upgrade head`).
3. Chamar `POST /internal/migrate` em **cada serviço da plataforma** registrado em
   seu service registry.

#### Service registry no config do platform-auth

```python
# app/core/config.py (apenas platform-auth)
PLATFORM_SERVICES: list[str] = [
    "http://platform-analytics:8000",
    "http://platform-connectors:8000",
    "http://platform-datalake:8000",
    "http://platform-scheduler:8000",
    "http://platform-cloud:8000",
    "http://platform-governance:8000",
    "http://platform-ml:8000",
    "http://platform-monitor:8000",
    "http://platform-docextract:8000",
]
```

#### Service de provisionamento no platform-auth

```python
# app/modules/tenants/services.py (platform-auth)
import asyncio
import httpx
import logging

logger = logging.getLogger(__name__)


async def _migrate_service(client: httpx.AsyncClient, base_url: str, tenant_id: str, token: str) -> dict:
    """Chama POST /internal/migrate em um serviço. Não-fatal em erro."""
    try:
        resp = await client.post(
            f"{base_url}/internal/migrate",
            json={"tenant_id": tenant_id},
            headers={"X-Internal-Token": token},
            timeout=60.0,
        )
        resp.raise_for_status()
        return {"url": base_url, "success": True}
    except Exception as exc:
        logger.error("Migration call failed | url=%s tenant=%s error=%s", base_url, tenant_id, exc)
        return {"url": base_url, "success": False, "error": str(exc)}


class TenantService:
    async def create(self, name: str) -> TenantResponse:
        """Provisiona novo tenant em toda a plataforma."""
        # 1. Idempotency check + INSERT em DB
        existing = await self._repo.get_by_name(name)
        if existing:
            raise ConflictError(f"Tenant '{name}' already exists.")
        row = await self._repo.create(name)
        tenant_id = str(row["id"])

        # 2. Roda as próprias migrations Alembic deste serviço
        from app.core.migrations import run_tenant_migration
        result = await run_tenant_migration(tenant_id)
        if not result["success"]:
            logger.error("Auth migration failed | tenant=%s", tenant_id)

        # 3. Propaga para todos os serviços da plataforma em paralelo
        async with httpx.AsyncClient() as client:
            tasks = [
                _migrate_service(client, url, tenant_id, settings.INTERNAL_API_TOKEN)
                for url in settings.PLATFORM_SERVICES
            ]
            results = await asyncio.gather(*tasks)

        failed = [r for r in results if not r["success"]]
        if failed:
            logger.warning(
                "Tenant %s: %d service(s) failed migration: %s",
                tenant_id, len(failed), [r["url"] for r in failed],
            )

        schema = _safe_schema(tenant_id)
        logger.info("Tenant provisioned | id=%s name=%s schema=%s", tenant_id, name, schema)
        return TenantResponse(id=tenant_id, name=name, schema_name=schema)
```

> Falhas de migration em serviços individuais são **logadas mas não-fatais** — o
> tenant continua sendo criado. Serviços que falharam podem ser re-migrados
> chamando seu endpoint `/internal/migrate` individualmente.

---

### 45.5 — Re-migration (idempotente)

`alembic upgrade head` é idempotente — seguro chamar múltiplas vezes. Se um
serviço perdeu a chamada inicial de provisioning, rode novamente:

```bash
# Do terminal do próprio serviço
alembic -x tenant_id=550e8400-e29b-41d4-a716-446655440000 upgrade head

# Ou via endpoint interno
curl -X POST http://platform-analytics:8000/internal/migrate \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "550e8400-e29b-41d4-a716-446655440000"}'
```

---

### 45.6 — Adições ao checklist de novo módulo

Ao adicionar novo módulo que tem tabelas de tenant:

- [ ] `alembic/versions/` contém a migration de tenant para a nova tabela
- [ ] `app/core/migrations.py` existe no serviço
- [ ] `app/core/auth_deps.py` existe com `require_internal_token`
- [ ] `app/api/internal.py` existe com `POST /internal/migrate`
- [ ] `internal_router` registrado em `app/main.py` (fora de `api_router`)
- [ ] `INTERNAL_API_TOKEN` presente em `app/core/config.py` e `.env.example`
- [ ] URL deste serviço adicionada a `PLATFORM_SERVICES` no config do platform-auth

---

---

## 46. Início rápido para agentes IA (quick reference)

Antes de escrever qualquer código, confirme:

| Verificação | Onde |
|-------------|------|
| O que este serviço possui (responsabilidade)? | §49 Mapa de responsabilidades por serviço |
| Como carregar `.env` no startup | §48 Perfis de ambiente |
| Estrutura de módulo / arquivos | §19 Estrutura de diretórios |
| Naming de DB (MySQL vs PostgreSQL) | §27 Convenções de nomenclatura no banco |
| Colunas de auditoria obrigatórias | §27 Convenções de nomenclatura no banco |
| Schema variable em SQL (`self._t()`) | §28 Convenções de queries SQL |
| Auth em todas as rotas | §44 Política de autenticação |
| Mudança em lib privada necessária? | §18 → HARD STOP |
| Template de config | §32 Template de `config.py` |
| Validação antes do PR | §33 Checklist de validação |

HARD STOPS estão em §15 e §50.4. Leia-os antes de tocar em qualquer arquivo.

---

## 47. Atribuições de portas — desenvolvimento local

Tabela canônica completa vive em [DEVOPS_STANDARDS.md §3](./DEVOPS_STANDARDS.md#3-port-allocation).
Resumo para agentes IA:

| Porta | Serviço | Prefixo do gateway |
|-------|---------|--------------------|
| 8000 | (reservada — nunca usar como host port) | — |
| 8001 | `platform-auth` | `/auth` |
| 8002 | `platform-admin` | `/admin` |
| 8003 | `platform-governance` | `/governance` |
| 8004 | `platform-analytics` | `/analytics` |
| 8005 | `platform-scheduler` | `/schedulers` |
| 8006 | `platform-connectors` | `/connectors` |
| 8007 | `platform-ml` | `/ml` |
| 8008 | `platform-cloud` | `/cloud` |
| 8009 | `platform-monitor` | `/monitor` |
| 8010 | `platform-notification` | `/notifications` |
| 8011 | `platform-communication` | `/communication` |
| 8012 | `platform-dataquality` | `/dataquality` |
| 8013 | `platform-docextract` | `/docextract` |
| 8014 | `dataforall-agents-factory` | `/agents` |
| 8015 | `dataforall-rag-service` | `/rag` |
| 8016 | `platform-datalake` | `/datalake` |
| 8017 | `platform-cdc` | — |
| 8018 | `platform-api-gateway` | — |
| 8019 | `platform-iceberg` | — |
| 8020 | `platform-flow` | `/flow` |
| 8021 | `platform-security` | `/security` |
| 8022–8029 | reservadas para futuros serviços | — |
| 8080 | `dataforall-ui-connect` | — |

> Em containers (Docker / K8s) todos os serviços rodam na porta interna `8000`.
> As portas acima são o **mapeamento host-side** apenas para docker-compose local.
> Cada serviço define `SERVICE_PORT` no seu compose (`${SERVICE_PORT:-8000}:8000`).

---

## 48. Perfis de ambiente — matriz de 5 perfis

> **Referência canônica:** [DEVOPS_STANDARDS.md §2](./DEVOPS_STANDARDS.md#2-environment-matrix--5-profiles).
> Esta seção é um resumo para agentes IA.

### Como funciona

Todos os serviços resolvem o `.env` ativo via `ENV_PROFILE` (um de 5 valores fixos).
A cascata é montada por `app/core/config.py::_resolve_env_files()`:

```python
# app/core/config.py — presente em TODOS os serviços
def _resolve_env_files() -> tuple[str, ...]:
    profile = os.getenv("ENV_PROFILE", "local-dev")
    files = [".env.defaults", f".env.{profile}", ".env.local", ".env"]
    legacy = os.getenv("APP_ENV_FILE")  # compat retroativa com §27 v1
    if legacy and legacy not in files:
        files.append(legacy)
    return tuple(files)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_resolve_env_files(), ...)
```

### Os 5 perfis

| `ENV_PROFILE` | `APP_ENV` | `RUNTIME_ENV` | `DEPLOY_TARGET` | Quando usar |
|---------------|-----------|---------------|------------------|-------------|
| `local-dev` | `dev` | `local` | `docker` | Dev no laptop via docker-compose (default) |
| `cloud-dev` | `dev` | `cloud` | `kubernetes` | Cluster K8s DEV |
| `local-hml` | `hml` | `local` | `docker` | Laptop reproduzindo configuração de HML |
| `cloud-hml` | `hml` | `cloud` | `kubernetes` | Cluster K8s HML/staging |
| `cloud-prod` | `prod` | `cloud` | `kubernetes` | Cluster K8s produção |

> `local-prod` é proibido — produção nunca roda em laptop.
> `ENVIRONMENT` (alias legado) é derivado automaticamente de `APP_ENV`:
> `dev` → `development`, `hml` → `staging`, `prod` → `production`.

### Cascata (arquivos posteriores ganham)

```
1. .env.defaults              ← commitado, valores comuns aos 5 perfis
2. .env.{ENV_PROFILE}         ← commitado, deltas do perfil ativo (sem secrets)
3. .env.local                 ← gitignorado, override pessoal do dev
4. process env / k8s secrets  ← maior precedência, prod injeta aqui
```

### Selecionando o perfil

```bash
# Default (sem var) → local-dev
docker compose up

# Override via env var
ENV_PROFILE=local-hml docker compose up

# Em Kubernetes Deployment env
env:
  - name: ENV_PROFILE
    value: cloud-prod

# Compat retroativa: APP_ENV_FILE ainda funciona (anexado ao final da cascata)
APP_ENV_FILE=.env.legacy.local uvicorn app.main:app
```

### Invariantes de perfil (forçadas no startup por `_enforce_profile_invariants`)

| Invariante | Quando dispara |
|------------|----------------|
| `ENV_PROFILE == "{RUNTIME_ENV}-{APP_ENV}"` | sempre |
| `RUNTIME_ENV=cloud` exige `DEPLOY_TARGET in {docker, kubernetes}` | sempre |
| `cloud-prod` rejeita `AUTH_DEV_BYPASS=true` | sempre |
| `cloud-prod` rejeita `CORS_ALLOWED_ORIGINS=["*"]` | sempre |
| `cloud-prod` exige `NETWORK_TOPOLOGY in {vpc, cross-network}` | sempre |

### Regras de git

| Arquivo | Commitar? | Notas |
|---------|-----------|-------|
| `.env.defaults` | SIM | valores base, sem secrets |
| `.env.local-dev` / `.env.cloud-dev` / `.env.local-hml` / `.env.cloud-hml` / `.env.cloud-prod` | SIM | templates de perfil, sem secrets |
| `.env.example` | SIM | documentação de referência |
| `.env.local.example` | SIM | template para override pessoal |
| `.env.local` | **NÃO** | override pessoal (gitignorado) |
| `.env` | **NÃO** | env ativa de `docker-compose.local.yml` (legado) |

### Valores compartilhados críticos (devem ser idênticos entre serviços)

| Variável | Compartilhada? | Regra |
|----------|----------------|-------|
| `JWT_SECRET_KEY` | **SIM — mesma em todos os serviços** | Todos validam tokens emitidos por `platform-auth` |
| `ADMIN_DB_HOST` / `ADMIN_DB_PORT` | Igual em todos os serviços MySQL | Coordenadas do MySQL de produção |
| `KAFKA_BOOTSTRAP_SERVERS` | Igual em todos por perfil | Hostname interno do cluster |
| `INTERNAL_API_TOKEN` | Igual em todos por perfil | Auth backend-to-backend — rotacionados juntos |
| `CREDENTIAL_ENCRYPTION_KEY` | Por serviço (ou compartilhado se compartilham creds) | Chave Fernet para credentials encrypted |

### Adições obrigatórias ao `.gitignore`

```gitignore
# Bloquear: em uso, pessoal, *.local
.env
.env.local
.env.*.local
# Permitir: defaults, perfis, examples
!.env.defaults
!.env.local-dev
!.env.cloud-dev
!.env.local-hml
!.env.cloud-hml
!.env.cloud-prod
!.env.example
!.env.local.example
```

---

## 49. Mapa de responsabilidades por serviço

Cada serviço possui um domínio bem-definido. **Um agente IA NUNCA deve implementar
funcionalidade que pertence a outro serviço.** Se você se encontrar escrevendo
lógica que outro serviço deveria possuir, pare e levante como questão cross-service.

### Cadeia de autorização

```
Request
  └─► platform-api-gateway  (roteamento, circuit breaker)
        └─► platform-auth    (validação de token / JWKS)
              └─► platform-governance  (RLS, permissões de módulo)
                    └─► {serviço alvo}  (lógica de negócio)
```

### Tabela de ownership

| Serviço | Possui | NÃO deve | Chama |
|---------|--------|----------|-------|
| **platform-auth** | Emissão de JWT, JWKS (`/.well-known/jwks.json`), service tokens, login/logout/refresh, coordenação de provisionamento de tenant, registry `PLATFORM_SERVICES` | Gestão de perfil de usuário, enforcement de permissão a nível de query | `platform-admin` (criação de tenant), todos os serviços via `/internal/migrate` |
| **platform-admin** | Usuários, domínios, tenants, perfis, times, role assignments, definições de IAM, endpoint `URL_IAM` | Emissão de JWT, enforcement de permissão a request time | `platform-auth` (introspecção de token) |
| **platform-governance** | Políticas de RLS, regras de row-level security, cache de permissões (`PERMISSION_CACHE_TTL_SECONDS`), controle de acesso a módulo | CRUD de usuário, emissão de token | `platform-admin` (definições de IAM via `URL_IAM`) |
| **platform-analytics** | Dashboards de BI, charts, queries salvas, dados live por WebSocket (`/ws/domains`, `/ws/analytics`) | Ingestão raw, computações ML, gestão de usuário | `platform-connectors` (metadata de fonte), `platform-ml` (resultados de modelo) |
| **platform-scheduler** | Definições de cron task, execução agendada, histórico de tasks, endpoint `URL_SCHEDULER` | Executar a lógica de negócio do que a task faz | `platform-pipeline` (disparar pipelines), outros serviços (via webhook/Kafka) |
| **platform-connectors** | Credenciais de fontes externas (40+ adapters), teste de conexão, gestão de `CREDENTIAL_ENCRYPTION_KEY` | Rodar pipelines, rodar ML, entregar dados | `platform-auth` (validação de token), `platform-datalake` (storage de arquivos) |
| **platform-ml** | NLP, OCR, clustering, time series, model serving, catálogo de algoritmos | Gestão de fontes de dados, orquestração de pipeline, scheduling | `platform-connectors` (dados de fonte), `platform-datalake` (artefatos de modelo) |
| **platform-cloud** | Provisionamento de infraestrutura (Terraform), gestão de recursos cloud, ciclo de vida de cluster | Deploy de aplicação (CI/CD), execução de pipeline | `platform-scheduler` (provisioning agendado) |
| **platform-monitor** | Regras de alerta, monitoramento de threshold, logs de execução de alertas, dispatch via webhook/email | Implementar lógica de negócio do que é monitorado (assina eventos de outros serviços) | `platform-communication` (enviar alertas), `platform-analytics` (métricas) |
| **platform-cdc** | Change Data Capture de DBs source → datalake, estado de replicação, eventos Kafka de CDC | Checks de qualidade, queries de analytics, execução de pipeline | `platform-connectors` (creds de source), `platform-datalake` (target) |
| **platform-docextract** | Parsing de documento (PDF/imagens → JSON estruturado), gestão de jobs de extração | Classificação ML do conteúdo extraído, gestão de storage | `platform-ml` (classificação), `platform-files-lib` (storage) |
| **dataforall-agents-factory** | Agentes IA, orquestração de LLM, histórico de chat, WebSocket `/chat`, execução de tools, configurações de agente | Treinamento ML raw, scheduling de tasks, entrega de email | `platform-ml` (inferência), `platform-scheduler` (tasks async), `platform-communication` (notificações) |
| **platform-datalake** | Metadata do data lake, catálogo de arquivos, queries DuckDB sobre parquet, API de acesso ao data lake | Execução de pipeline, enforcement de qualidade, ingestão de dados | `platform-files-lib` (storage), `platform-dataquality` (checks de qualidade) |
| **platform-pipeline** | Definições de pipeline, grafo de execução, orquestração de step, histórico | Steps de ML (delegar a platform-ml), acesso a connector (via platform-connectors), scheduling (→ platform-scheduler) | `platform-ml`, `platform-connectors`, `platform-scheduler`, `platform-datalake` |
| **platform-communication** | Entrega de email, SMS, WhatsApp, push notifications, gestão de canal, templates de mensagem | Lógica de roteamento de notificação, gestão de preferências de usuário | `platform-admin` (info de contato do usuário), provedores externos (SMTP, Twilio, etc.) |
| **platform-dataquality** | Regras de qualidade de dados, runs de validação, métricas de qualidade, relatórios DQ | Ingestão de dados, execução de pipeline, escritas no data lake | `platform-datalake` (ler dados), `platform-connectors` (metadata de source) |
| **platform-notifications** | WebSocket push para `/ws/notifications` (pessoal) e `/ws/queue` (progresso de task) | Enviar mensagens reais (→ communication), gerar conteúdo de notificação (cada serviço publica eventos Kafka) | Kafka (consome eventos `user.notification`, `task.*`) |

### Regras de comunicação cross-service

**HTTP (síncrono):**
- Sempre use o client lib público do serviço: `from platform_{service}.client import ServiceClient`
- URLs de serviço vêm da config: `settings.URL_AUTH`, `settings.URL_IAM`, `settings.URL_SCHEDULER`
- Nunca defina seu próprio HTTP client para outro serviço inline

**Kafka (assíncrono):**
- Publicar evento Kafka NÃO significa que o serviço publicador possui o domínio do consumidor
- `platform-auth` publica `user.created` → `platform-notifications` consome → push WS notification.
  `platform-auth` NÃO deve enviar notificações por si.

**Endpoints internos (`/internal/*`):**
- Apenas `platform-auth` chama `/internal/migrate` em outros serviços (provisionamento de tenant)
- Nunca chame `/internal/migrate` a partir de lógica de negócio de módulo

---

## 50. Modelo operacional de agentes IA

### 50.1 — Antes de escrever qualquer código

1. Leia §49 — confirme que está no serviço certo para esta feature
2. Leia §27 — verifique naming de DB para o engine deste serviço (PostgreSQL ou MySQL)
3. Abra `alembic/versions/` — verifique nomes de coluna ANTES de escrever SQL
4. Leia o `AGENTS.md` próprio do serviço para overrides específicos

### 50.2 — Operações seguras (não precisam confirmação)

- Ler qualquer arquivo do serviço
- Adicionar / editar testes em `tests/`
- Adicionar novo módulo seguindo o padrão de 7 arquivos (§23)
- Criar arquivos de migration Alembic
- Editar `.env.example` (documentação)
- Atualizar `schemas.py`, `mappers.py`, `handlers.py`

### 50.3 — Operações que exigem cuidado

- Editar `app/core/config.py` — verifique que todos campos obrigatórios continuam após mudança
- Editar `app/core/database.py` — afeta todas as conexões DB
- Editar `app/main.py` — verifique ordem da stack de middleware (§22) após mudança
- Adicionar dependência em `requirements.txt` — rode `pip-audit` antes
- Editar `alembic/env.py` — afeta TODAS as migrations

### 50.4 — HARD STOPS — pare imediatamente e reporte ao usuário

(Itens complementares aos §15 — focados no template Python/FastAPI)

1. **Mudança em lib privada necessária** (§18): qualquer task que exige edit em
   `platform-*-lib` → LIB CHANGE REQUEST → aguardar aprovação `@caiog`
2. **Rota pública detectada**: `APIRouter` sem `dependencies=[Depends(jwt_manager)]`
   → adicione antes de prosseguir (§44)
3. **SQL com coluna inexistente**: coluna não está na migration → crie migration
   primeiro, nunca presuma (§28)
4. **Lógica que pertence a outro serviço**: ver tabela de ownership §49 → levante
   como questão cross-service
5. **Commitando arquivo `.env.*`** (que não seja `.env.example`) → violação de
   segurança, nunca commite
6. **Secret hardcoded em código**: `JWT_SECRET_KEY = "abc"` ou similar → mover
   para env imediatamente
7. **`AUTH_DEV_BYPASS = True` deixado habilitado**: deve ser `False` em qualquer
   código commitado

### 50.5 — Checklist de segurança antes de cada PR

- [ ] Sem secrets ou API keys hardcoded em qualquer arquivo
- [ ] Sem `AUTH_DEV_BYPASS = True` em código commitado
- [ ] Todas as rotas sob `/api/v1/` têm dependency `jwt_manager`
- [ ] Todo SQL usa placeholders `$1, $2` (sem f-string SQL com user data)
- [ ] Todas as leituras filtram `WHERE is_deleted = FALSE`
- [ ] Sem `"*"` em `CORS_ALLOWED_ORIGINS` quando `ENVIRONMENT=production`
- [ ] `pip-audit` passa
- [ ] Sem arquivos `.env.*` staged em git

### 50.6 — Workflow de desenvolvimento local

```bash
# 1. Copie e configure arquivo de env
cp .env.example .env.dev.local
# Edite .env.dev.local — preencha JWT_SECRET_KEY (compartilhado de platform-auth), valores DB_*

# 2. Inicie o serviço
APP_ENV_FILE=.env.dev.local uvicorn app.main:app --reload --port {PORT}

# 3. Rode migrations compartilhadas
APP_ENV_FILE=.env.dev.local alembic upgrade head

# 4. Rode migrations de tenant (para tenant_id=1 local)
APP_ENV_FILE=.env.dev.local alembic -x tenant_id=1 upgrade head

# 5. Rode os testes
APP_ENV_FILE=.env.dev.local pytest tests/ -x --tb=short --cov=app --cov-fail-under=70
```

### 50.7 — Quando implementar uma feature nova

1. Confirme que a feature pertence a este serviço (§49)
2. Identifique o módulo — crie `app/modules/{feature}/` se for novo
3. Escreva migration primeiro — depois repository — depois service — depois router
4. Atualize `src/platform_{service}/schemas.py` com tipos de response públicos
5. Atualize `API_CONTRACT.md` com novos endpoints
6. Escreva testes antes de marcar como completo
7. Rode checklist completo de validação (§33)

---

## 51. Modo LAB — playground manual & de agentes IA

Toda nova ou existente implementação de microsserviço **deve** seguir o
padrão LAB descrito em [docs/lab-pattern.md](docs/lab-pattern.md). Em
resumo:

- Pacote isolado em `app/lab/` (router + middleware + UI + mocks).
- Master switch `LAB_MODE` (default `false`); **bloqueado em `cloud-prod`**
  pelo validator em `_enforce_profile_invariants` (defesa em profundidade).
- `mount_lab(app, settings)` é chamado uma única vez em `app/main.py`
  *após* os routers de produção. É no-op quando `is_lab_enabled` é falso.
- `TenantMiddleware` é registrado via `PathConditionalMiddleware` quando
  LAB está ativo, para `/lab/*` pular validação de tenant *sem* afetar
  `/api/v1/*`.
- Endpoints expostos: `/lab` (landing), `/lab/health`, `/lab/info`,
  `/lab/docs`, `/lab/openapi.json`, `/lab/test`, `/lab/items*`,
  `/lab/agents/*` (opt-in via `LAB_AGENTS_ENABLED`).

### Quando aplicar

- **Sempre** em serviços novos criados a partir deste template (já vem
  pronto — não precisa fazer nada).
- **Sempre** em serviços com agentes IA de primeira classe
  (`dataforall-agents-factory`, `dataforall-rag-service`, `platform-ml`).
- **Migrar** serviços que já têm um LAB ad-hoc para o padrão canônico
  (atual: `platform-cloud`, `platform-connectors` — ver §migrate-existing
  do runbook).

### Como aplicar em um serviço existente

Siga o runbook: [docs/runbooks/adopt-lab-pattern.md](docs/runbooks/adopt-lab-pattern.md)
(10 passos, ~30 min de trabalho líquido).

### Proibições

- Nunca expor `/lab/*` no `platform-api-gateway` ou em Ingress de produção.
- Nunca importar de `app/modules/*` dentro de `app/lab/*` (define schemas
  locais — ver `_LabItemCreate` em `app/lab/routers/playground.py`).
- Nunca persistir dados reais quando `USE_MOCK_DATA=true` — handlers LAB
  devem inspecionar `request.state.lab_use_mock_data` e respeitar.

---

## 52. Prompt de agente Terraform / SRE

> Esta seção define as regras obrigatórias que todo agente de IA atuando em
> infraestrutura (Terraform, IaC, SRE) deve seguir. O conteúdo abaixo **deve
> ser incluído** no system-prompt de qualquer agente Terraform / SRE do
> ecossistema `dataforalltech`.

---

### 52.1 — CLIs, tooling e artefatos

O agente deve garantir que todas as CLIs necessárias estejam sempre instaladas
e disponíveis **antes** de executar qualquer operação de infraestrutura.

**CLIs obrigatórias:**

| CLI | Condição |
|-----|----------|
| `terraform` | sempre |
| `az` | sempre |
| `docker` | sempre |
| `git` | sempre |
| `gh` | sempre |
| `jq` | sempre |
| `yq` | sempre |
| `kubectl` | quando houver Kubernetes |
| `helm` | quando houver Helm |

**Regras:**

- Antes de executar qualquer comando, validar versão e disponibilidade das CLIs.
- Se alguma CLI estiver ausente, documentar a instalação necessária e **não
  prosseguir**.
- Nunca executar `terraform plan`, `terraform apply`, deploy ou rollback sem
  validar o tooling mínimo.
- Registrar no documento os comandos de verificação.

**Exemplo de verificação:**

```bash
terraform version
az version
docker version
git --version
gh --version
kubectl version --client
helm version
jq --version
yq --version
```

---

### 52.2 — Backup de artefatos

Todos os artefatos gerados, modificados ou utilizados pelos pipelines e agentes
devem possuir estratégia de backup via `platform-connector` (ver §52.3).

**O que é considerado artefato:**

- Arquivos Terraform (`.tf`, `.tfvars`)
- Planos Terraform (`terraform.plan`)
- Outputs Terraform (`terraform output -json`)
- Manifests gerados (Kubernetes YAML, Helm values)
- Arquivos de configuração de ambiente
- Relatórios de auditoria
- Documentação gerada
- Logs relevantes de execução
- Evidências de execução (screenshots, JSONs de resultado)
- Arquivos de deploy
- Templates de pipeline
- Artefatos de build

**Regras:**

- Todo artefato crítico deve ser salvo em repositório/armazenamento configurado
  via `platform-connector`.
- O backup deve ocorrer **antes** de alterações destrutivas.
- O backup deve ocorrer **após** geração de novos artefatos.
- Artefatos devem ser versionados por: serviço, ambiente, data/hora, commit SHA
  e tipo de artefato.

**Padrão de organização:**

```text
artifacts/
 ├── terraform/
 │    ├── dev/
 │    ├── hml/
 │    └── prod/
 ├── pipelines/
 ├── deployments/
 ├── audits/
 ├── docs/
 └── logs/
```

---

### 52.3 — Integração com `platform-connector`

O agente deve verificar se existe uso ou disponibilidade da biblioteca
`platform-connector` no repositório alvo.

**Se existir, deve propor ou implementar integração para:**

- Upload de artefatos
- Download de artefatos
- Recuperação de versões anteriores
- Backup antes de `apply` / deploy
- Backup de evidências de execução
- Armazenamento de relatórios

**Regras:**

- Não criar solução paralela se `platform-connector` já resolver o problema.
- Usar `platform-connector` como abstração oficial — nenhum cliente de storage
  ad-hoc é aceito.
- Caso a biblioteca ainda não esteja integrada no repositório alvo, propor a
  integração como tarefa separada.
- Documentar claramente como os agentes devem usar essa biblioteca.

---

### 52.4 — Entregáveis adicionais obrigatórios

Qualquer PR de agente Terraform / SRE deve incluir (ou atualizar) os seguintes
documentos em `docs/devops/`:

| Arquivo | Conteúdo obrigatório |
|---------|----------------------|
| `docs/devops/tooling-requirements.md` | Lista oficial de CLIs, como validar instalação, como instalar dependências ausentes, regras para agentes MCP |
| `docs/devops/artifact-backup-strategy.md` | Estratégia de backup, convenção de nomes dos artefatos, procedimento de recuperação |
| `docs/devops/platform-connector-usage.md` | Uso oficial da biblioteca `platform-connector`, exemplos de upload/download/recuperação |

Cada documento deve cobrir:

1. Lista oficial de CLIs obrigatórias.
2. Como validar instalação.
3. Como instalar dependências ausentes.
4. Estratégia de backup de artefatos.
5. Convenção de nomes dos artefatos.
6. Uso oficial da biblioteca `platform-connector`.
7. Procedimento de recuperação de artefatos.
8. Regras para agentes MCP.

---

### 52.5 — Ferramentas MCP aprovadas para agentes Terraform / SRE

#### Obrigatórias

Sem estas ferramentas o agente **não deve iniciar** nenhuma operação de
infraestrutura.

| Ferramenta MCP | Finalidade |
|----------------|-----------|
| `mcp-filesystem` | Ler e escrever arquivos `.tf`, `.tfvars`, planos, manifests e configs localmente |
| `mcp-git` | Verificar diff de IaC, checar histórico de state, commitar mudanças versionadas |
| `mcp-github` | Abrir PRs de mudança de infra, verificar aprovações, bloquear apply sem review |
| `mcp-shell` | Executar `terraform`, `az`, `kubectl`, `helm` com output capturado e auditável |

#### Fortemente recomendadas

| Ferramenta MCP | Finalidade |
|----------------|-----------|
| `mcp-azure` | Introspecção de recursos Azure sem depender de `az` — consultar estado real antes de planejar mudança |
| `mcp-kubernetes` | Inspecionar estado de cluster, pods e deployments — validação pós-apply |
| `mcp-fetch` | Health check de endpoints após deploy — confirmar que o serviço respondeu corretamente |
| `mcp-docker` | Inspecionar imagens, verificar digest antes de referenciar em manifests |
| `mcp-slack` | Notificar canal SRE em operações críticas (apply em prod, destroy, rollback) |

#### Governança e segurança

| Ferramenta MCP | Finalidade |
|----------------|-----------|
| `mcp-checkov` / `mcp-tfsec` | Scan de policy-as-code **antes** do plan — HARD STOP se falhar |
| `mcp-vault` | Ler segredos do HashiCorp Vault sem nunca expô-los em logs ou state |
| `mcp-infracost` | Estimativa de custo antes do apply — agente não aplica se delta exceder threshold definido |

#### Observabilidade pós-deploy

| Ferramenta MCP | Finalidade |
|----------------|-----------|
| `mcp-prometheus` | Verificar métricas de saúde após mudança de infra |
| `mcp-grafana` | Confirmar que dashboards de SLO não degradaram após apply |

#### Ferramentas proibidas

| Proibição | Motivo |
|-----------|--------|
| MCP com write direto em prod sem gate de aprovação | Agente pode *planejar* e *propor*, nunca aplicar em prod sozinho |
| MCP de cloud com permissão `Owner` ou `Contributor` global | Usar identidades de menor privilégio: `Reader` para plan, `Contributor` limitado para apply em hml |
| MCP que exponha secrets em texto claro | Tudo que toca credencial deve passar por Vault ou Key Vault reference |
| MCP com acesso a `terraform destroy` em prod | Operação destrutiva em prod é HARD STOP — requer escala humana |

#### Regra de ouro

```text
O agente MCP PODE:    ler estado, planejar mudanças, propor PR, notificar equipe.
O agente MCP NÃO PODE: aplicar em prod sem aprovação humana registrada no PR.
```

#### Permissões mínimas por ambiente

| Ambiente | Permissão de identidade do agente |
|----------|----------------------------------|
| `local-dev` | Contributor no resource group de dev |
| `dev` | Contributor no resource group de dev |
| `hml` | Contributor no resource group de hml — aprovação automática via CI |
| `cloud-staging` | Reader para plan; Contributor exige aprovação de 1 engenheiro |
| `cloud-prod` | Reader para plan; Contributor exige aprovação de 2 engenheiros + issue aberta |

---

### 52.6 — Sandbox de dev cloud individual

> Esta subseção define o regime aplicável a infraestrutura cloud provisionada
> exclusivamente para uso individual de um desenvolvedor (workstation remoto,
> dev sandbox, ambiente de exploração pessoal). Cobre o gap entre §52.1–52.5
> — orientado a infra de produção dos serviços `platform-*` — e a realidade
> de ferramentas pessoais de desenvolvimento.

#### 52.6.1 — Critérios de aplicabilidade

Uma infra qualifica-se como **sandbox de dev individual** se **todos** os
critérios abaixo são verdadeiros:

1. Provisionada para uso de **um único desenvolvedor identificado** (tag
   `Owner=<handle>`).
2. **Não** hospeda nenhum serviço `platform-*` em produção, hml ou
   cloud-staging.
3. **Não** participa de pipelines de CI/CD do ecossistema.
4. **Não** está exposta na internet sem autenticação forte (Tailscale,
   Cloudflare Access, AWS SSM, ou equivalente).
5. **Não** tem peering, IAM cross-account ou qualquer rota para recursos
   de produção.
6. Custo mensal estimado **abaixo de US$ 200**. Acima disso aplica-se o
   regime padrão §52.1–52.5.
7. Vida útil **temporária ou descartável** — recursos podem ser destruídos
   sem coordenação com terceiros.

Se algum critério falha, a infra **deixa de ser sandbox** e se enquadra em
§52.1–52.5.

#### 52.6.2 — Regras dispensadas

Estas exigências de §52.1–52.5 **não** se aplicam a sandboxes individuais:

| Regra dispensada | Motivo |
|------------------|--------|
| §52.1 `az` CLI obrigatório | Sandbox pode usar provedor único (AWS, GCP) sem Azure |
| §52.2 Backup via `platform-connector` | Estado pertence ao dev individual; backup local + remote backend pessoal (S3/GCS bucket próprio) é suficiente |
| §52.3 Integração com `platform-connector` | Lib é para artefatos de plataforma, não para dev individual |
| §52.4 `docs/devops/tooling-requirements.md`, `artifact-backup-strategy.md`, `platform-connector-usage.md` | Substituídos pelo `README.md` do próprio diretório do sandbox |

#### 52.6.3 — Regras que continuam obrigatórias

Mesmo em sandbox individual, **mantém-se obrigatório**:

1. **ADR registrando a criação do sandbox**
   (`docs/decisions/adr-NNNN-sandbox-<nome>.md`), incluindo: dono, escopo,
   custo estimado, mecanismo de auto-stop, plano de teardown, lista das
   regras de §52 que estão dispensadas e por quê.
2. **README dedicado** no diretório do sandbox
   (`infra/<sandbox-name>/README.md`) com: setup, custos, comando de
   teardown, justificativa explícita de cada dependência adicionada.
3. **Tags AWS/GCP/Azure** padronizadas:
   `Owner=<handle>`, `Component=dev-sandbox`, `Project=<nome>`,
   `ManagedBy=terraform`.
4. **Hardening mínimo de segurança**:
   - IMDSv2 obrigatório (`http_tokens = "required"` em AWS).
   - Disco encriptado por padrão (EBS, Persistent Disk, Managed Disk).
   - Security groups **sem** `0.0.0.0/0` em portas de serviço — apenas via
     Tailscale, SSM Session Manager, Cloudflare Access ou IP fixo do dono.
   - IAM role com **menor privilégio** (Reader + ECR/ACR pull). Nunca Owner
     ou Contributor global.
5. **Auto-stop ou orçamento explícito**:
   - Configurar auto-stop por idle, **OU**
   - Budget alarm no provedor com threshold de 1.5× do custo estimado.
6. **Plano de teardown documentado** (`terraform destroy` ou equivalente) —
   sem recursos órfãos previstos.
7. **Sem credencial de produção** dentro do sandbox: nada de chaves de prod,
   nada de peering, nada de secrets do cofre corporativo.

#### 52.6.4 — Regras recomendadas (não bloqueantes)

- `tfsec` ou `checkov` no `terraform plan` do sandbox antes do primeiro apply.
- `infracost` rodado no PR que cria o sandbox.
- Backup do `terraform.tfstate` em remote backend pessoal (S3/GCS bucket do
  dev) com versionamento ligado.
- Teste de teardown imediatamente após primeiro provisionamento, para
  validar que `destroy` é idempotente.

#### 52.6.5 — HARD STOPS específicos de sandbox

Adicionados aos hard stops gerais de §15:

| # | Situação | Ação |
|---|----------|------|
| S1 | Sandbox precisa de peering, VPC sharing ou IAM cross-account com prod | Parar. Não é mais sandbox. Aplicar §52.1–52.5 ou redesenhar |
| S2 | Sandbox vai expor serviço público sem autenticação forte | Parar. Documentar autenticação em ADR antes de seguir |
| S3 | Custo estimado (ou observado) ultrapassou US$ 200/mês | Parar. Aplicar §52.1–52.5 |
| S4 | Sandbox vai compartilhar credencial entre múltiplos devs | Parar. Não é mais "individual" — aplicar §52.1–52.5 |

#### 52.6.6 — Localização canônica

Sandboxes individuais ficam sob `infra/<sandbox-name>/`:

```
infra/
└── <sandbox-name>/
    ├── README.md
    ├── .gitignore                 # bloqueia *.tfstate, *.tfvars (deixa .example passar)
    ├── terraform/
    │   ├── versions.tf
    │   ├── variables.tf
    │   ├── main.tf
    │   ├── outputs.tf
    │   ├── terraform.tfvars.example
    │   └── .terraform.lock.hcl
    ├── userdata.sh                # cloud-init (opcional)
    └── bootstrap.sh               # provisioning script (opcional)
```

#### 52.6.7 — Promoção de sandbox a infra de plataforma

Se um sandbox provar valor coletivo e precisar virar infra compartilhada:

1. Abrir novo ADR substituindo o ADR original do sandbox (status:
   `substituido`).
2. Mover de `infra/<sandbox-name>/` para o local apropriado (ex.: novo repo
   `platform-<area>-infra`, ou `infra/shared/`).
3. Aplicar §52.1–52.5 integralmente: backup via `platform-connector`,
   `docs/devops/*`, gates de aprovação por ambiente.
4. Migrar o estado e credenciais para identidades compartilhadas.

---

## 53. Trinity Pattern — API + Lib + MCP Architecture

O **Trinity Pattern** define que todo microserviço (exceto bibliotecas puras) deve expor
**três componentes** coexistindo no mesmo repositório:

```
Microserviço = REST API + Installable Lib + MCP Server
```

### 53.1 — O que é Trinity?

| Camada | Propósito | Quando usar | Output |
|--------|-----------|-----------|--------|
| **REST API** (`app/`) | Endpoints HTTP para clientes web/mobile | Sempre | FastAPI server:8001 |
| **Lib** (`src/`) | Pacote Python instalável (consumo interno) | Sempre | PyPI privado |
| **MCP** (`mcp/`) | Model Context Protocol para agentes IA | Serviços públicos + ferramentas | stdio |

**Por que Trinity?**
- **Eficiência de IA**: Agentes IA executam tarefas via MCP com zero latency (stdio, não HTTP)
- **Reutilização**: Uma lib para clientes Python, scripts, agentes
- **Consistência**: Mesma lógica versionada em 3 interfaces simultaneamente
- **Operacional**: Cada camada escala independentemente

### 53.2 — Aplicabilidade

Trinity é **obrigatório** para:
- ✅ Todos os 21 Core Services
- ✅ Ops Services que usam agentes (scheduler, pipeline, governance)
- ✅ Services públicos

**Opcionais** (não exigem MCP):
- ⚪ Libs puras (`src/` somente, sem `app/`)
- ⚪ Frontends React/Next.js (têm `app/` REST, não precisam `src/` lib ou MCP)

### 53.3 — Estrutura obrigatória

```
platform-<service>/
├── app/                          # REST API
│   ├── main.py, api/, core/, modules/, ...
├── src/                          # Installable Lib
│   └── platform_<service>/ (schemas, client, events)
├── mcp/                          # MCP Server ← NOVO
│   ├── pyproject.toml
│   ├── src/
│   │   ├── config/settings.py
│   │   ├── client/api_client.py
│   │   ├── server/mcp_server.py
│   │   └── tools/<domain>_tools.py
│   └── tests/
├── tests/
├── Dockerfile                    # App container
├── pyproject.toml                # Root (governa app + src)
└── .github/workflows/
    ├── ci.yml                    # Inclui jobs lint-mcp, test-mcp
    └── version-tag.yml
```

- Cada layer é pacote Python independente mas versionado junto.
- **mcp/pyproject.toml** é separado do raiz (permite evolução independente).
- CI/CD processa todos os 3 layers: lint, test, build, deploy.

Veja [docs/architecture/trinity-pattern.md](docs/architecture/trinity-pattern.md) para
estrutura completa, responsabilidades, contratos e checklist de conformidade.

### 53.4 — Como o MCP se comunica com a API

O MCP **não importa código do app/** ou **src/**. É um **wrapper HTTP**:

```
Agente IA
  └─→ MCP Server (stdio)
       └─→ HTTP Client (httpx)
            └─→ REST API (:8001)
                 └─→ App logic, database
```

**Benefícios:**
- Desacoplamento completo (MCP é sidecar)
- Funciona em dev (localhost:8001) e prod (intra-pod networking)
- MCP não precisa de acesso ao banco (somente HTTP)
- Fácil de testar (mock do http client)

---

## 54. MCP Standards — Nomenclatura, Implementação, Governance

> **Nota sobre MCPs operacionais:** O `mcp/` neste template é um exemplo de referência para
> implementar o Trinity Pattern. Os 11 servidores MCP operacionais da plataforma (session, test,
> docs, services, pipeline, qa, deploy, agent-twin, config, infra, ai-governance) foram
> migrados para [platform-devs](https://github.com/dataforalltech/platform-devs).
>
> **Se está desenvolvendo para a plataforma:** leia a documentação em `platform-devs`.
> **Se está criando um novo serviço:** use este `mcp/` como template e siga as regras abaixo.

### 54.1 — Tool Naming Convention

Format obrigatório: `<service>_<verb>_<subject>`

```
Correto: auth_create_token, scheduler_trigger_job, api_list_resources
Errado:  auth_token, do_auth, callAPI, service_action
```

**Verbos permitidos:** `create`, `get`, `list`, `update`, `delete`, `validate`, `trigger`, `check`

**Regras:**
- Sem abreviações (`authenticate` não `auth`, `validate` não `validate_param`)
- Snake case obrigatório
- 1 tool = 1 operação (não multi-op tools como `service_manage_user(action=...)`)

### 54.2 — Tool Definition

```python
from mcp.types import Tool

Tool(
    name="service_verb_subject",
    description="One-line description. What it does, not how.",
    inputSchema={
        "type": "object",
        "properties": {
            "param_name": {
                "type": "string",
                "description": "What this parameter does"
            }
        },
        "required": ["param_name"]
    }
)
```

**Descrição:** Explique O QUE a ferramenta faz, não COMO. Seja claro para agentes IA.

### 54.3 — Response Format

Sempre retornar `list[TextContent]` com JSON:

```python
# Sucesso (200–299)
[TextContent(type="text", text=json.dumps({
    "status": "ok",
    "data": {...}
}))]

# Erro cliente (400, 404, 422)
[TextContent(type="text", text=json.dumps({
    "error": "BadRequest|NotFound|ValidationError",
    "details": "human-readable message"
}))]

# Erro servidor (500+)
[TextContent(type="text", text=json.dumps({
    "error": "InternalError",
    "details": "HTTP 500: Service unavailable"
}))]

# Exceção Python (não capturada)
[TextContent(type="text", text=json.dumps({
    "error": "InternalError",
    "details": "str(exception)"
}))]
```

**Regra:** Nunca lance exceptions do MCP. Sempre capture, logue, retorne JSON.

### 54.4 — API Client & Configuration

```python
# mcp/src/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    service_base_url: str = "http://localhost:8001"
    service_token: str  # obrigatório
    log_level: str = "INFO"
    request_timeout: float = 30.0
    
    model_config = SettingsConfigDict(
        env_prefix="MCP_SERVICE_",
        case_sensitive=False
    )
```

**Variáveis de ambiente obrigatórias:**
- `MCP_SERVICE_BASE_URL` — URL da API (default: http://localhost:8001)
- `MCP_SERVICE_TOKEN` — Bearer token (obrigatório)
- `MCP_SERVICE_LOG_LEVEL` — INFO, DEBUG, WARNING, ERROR
- `MCP_SERVICE_REQUEST_TIMEOUT` — timeout em segundos

```python
# mcp/src/client/api_client.py
import httpx
from .config.settings import Settings

class ServiceApiClient:
    def __init__(self, settings: Settings):
        self._client = httpx.AsyncClient(
            base_url=settings.service_base_url,
            headers={"Authorization": f"Bearer {settings.service_token}"},
            timeout=settings.request_timeout,
        )
    
    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.get(path, **kwargs)
```

### 54.5 — MCP Server Structure

```python
# mcp/src/server/mcp_server.py
from mcp import Server, Tool
from mcp.types import TextContent
from ..config.settings import Settings
from ..client.api_client import ServiceApiClient
from ..tools import service_tools

settings = Settings()
api_client = ServiceApiClient(settings)
server = Server("service")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="service_get_user",
            description="Retrieve a user by ID",
            inputSchema={...}
        ),
        Tool(
            name="service_create_user",
            description="Create a new user",
            inputSchema={...}
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "service_get_user":
        return await service_tools.service_get_user(**arguments)
    elif name == "service_create_user":
        return await service_tools.service_create_user(**arguments)
    else:
        return [TextContent(type="text", text=json.dumps({
            "error": "NotFound",
            "details": f"Tool {name} not found"
        }))]

def main():
    import asyncio
    asyncio.run(server.run(use_stdio=True))

if __name__ == "__main__":
    main()
```

### 54.6 — Tool Implementation

```python
# mcp/src/tools/service_tools.py
import json
from mcp.types import TextContent
from ..client.api_client import ServiceApiClient
from ..config.settings import Settings

settings = Settings()
api_client = ServiceApiClient(settings)

async def service_get_user(user_id: str) -> list[TextContent]:
    """Retrieve a user by ID."""
    try:
        response = await api_client.get(f"/users/{user_id}")
        
        if response.status_code == 404:
            return [TextContent(type="text", text=json.dumps({
                "error": "NotFound",
                "details": f"User {user_id} not found"
            }))]
        
        if response.status_code >= 500:
            return [TextContent(type="text", text=json.dumps({
                "error": "InternalError",
                "details": f"API returned {response.status_code}"
            }))]
        
        if response.status_code == 200:
            return [TextContent(type="text", text=json.dumps({
                "status": "ok",
                "data": response.json()
            }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": "InternalError",
            "details": str(e)
        }))]
```

### 54.7 — Governance Rules (MUST)

| Regra | Aplicação | Violação |
|-------|-----------|----------|
| 1 tool = 1 operação | `service_create_user`, `service_delete_user` | `service_manage_user(action=...)` |
| MCP via HTTP só | `await api_client.get(...)` | `await db.query(...)` |
| Config via settings | `settings.service_token` | `token = "hardcoded"` |
| Error handling | `return {"error": "..."}` | `raise Exception(...)` |
| Sem lógica negócio | `MCP → API → logic` | `async def tool(): business_logic()` |
| Tests com mock | `monkeypatch api_client` | `test hit real API` |
| Sem sensitive logs | `logger.info("Authenticated")` | `logger.info(f"Token: {token}")` |

### 54.8 — Testing & CI/CD

**Test structure:**
```
mcp/tests/
├── conftest.py                     # Fixtures
├── test_<domain>_tools.py          # Tool tests (mock api_client)
└── test_server.py                  # Server tests
```

**CI/CD jobs (add to ci.yml):**
```yaml
lint-mcp:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: cd mcp && ruff check src/ && mypy src/

test-mcp:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: cd mcp && pip install -e ".[dev]"
    - run: cd mcp && pytest tests/ -v --cov=src --cov-report=term-missing
```

### 54.9 — Pre-deploy Checklist

□ `mcp/pyproject.toml` com name = `<service>-mcp`
□ Tools nomeados como `<service>_<verb>_<subject>`
□ Cada tool documenta parâmetros e tipos
□ Tools retornam `list[TextContent]` com JSON válido
□ Erros retornam `{"error": "...", "details": "..."}`, nunca exceptions
□ API client usa settings (não hardcoded)
□ MCP não acessa banco (somente HTTP)
□ Tests cobrem >70% (mock api_client)
□ ci.yml tem jobs `lint-mcp` e `test-mcp`
□ GitHub Secrets: `MCP_<SERVICE>_BASE_URL`, `MCP_<SERVICE>_TOKEN`
□ AGENTS.md local referencia `docs/architecture/trinity-pattern.md`
□ Version sincronizada com `app/` + `src/` (via VERSION_POLICY.md)

Referência completa: [docs/architecture/trinity-pattern.md](docs/architecture/trinity-pattern.md)

---

## Recursos auxiliares deste repositório

| Arquivo | Propósito |
|---------|-----------|
| [docs/ai-agents/response-template.md](docs/ai-agents/response-template.md) | Formato canônico de resposta do agente (referenciado em §13) |
| [docs/ai-agents/pre-flight-checklist.md](docs/ai-agents/pre-flight-checklist.md) | Checklist pré-implementação (referenciado em §5) |
| [docs/ai-agents/templates/AGENTS-nextjs.md](docs/ai-agents/templates/AGENTS-nextjs.md) | Template de Parte II para frontends Next.js / React |
| [docs/ai-agents/templates/AGENTS-libs-js.md](docs/ai-agents/templates/AGENTS-libs-js.md) | Template de Parte II para libs TypeScript publicadas em npm |
| [docs/lab-pattern.md](docs/lab-pattern.md) | Padrão canônico do modo LAB (design, contratos, decisões) — referenciado em §51 |
| [docs/runbooks/adopt-lab-pattern.md](docs/runbooks/adopt-lab-pattern.md) | Runbook de adoção do LAB em outros serviços (10 passos) |
| [scripts/propagate-agents-md.sh](scripts/propagate-agents-md.sh) | Script para propagar este AGENTS.md aos demais ~35 repos do ecossistema |
| [.claude/hooks/block-lib-edits.sh](.claude/hooks/block-lib-edits.sh) | Hook PreToolUse que bloqueia edits em `platform-*-lib/` (enforce de §18) |
| [.claude/hooks/block-dangerous-commands.sh](.claude/hooks/block-dangerous-commands.sh) | Hook PreToolUse que bloqueia `--no-verify`, force push, etc. (enforce de §2 / §15) |
| [.claude/settings.json](.claude/settings.json) | Configuração dos hooks (versionada, escopo de projeto) |

### Como propagar este AGENTS.md aos outros repos

Crie um arquivo `repos.txt` listando os repos alvo (1 por linha; aceita
campo `stack=<nome>` opcional para usar template específico). Exemplo:

```
# backends Python — usam pointer (Parte I + Parte II do template canônico)
../platform-analytics
../platform-cdc

# frontends — usam template Next.js como Parte II local
../webapp-admin   stack=nextjs
../webapp-portal  stack=nextjs

# libs JS — usam template libs-js como Parte II local
../lib-types      stack=libs-js
```

Depois rode:

```bash
# Pré-visualizar (dry-run, sem aplicar)
bash scripts/propagate-agents-md.sh --strategy stack --repos repos.txt --dry-run

# Aplicar localmente nos repos (cria branch, sem commit)
bash scripts/propagate-agents-md.sh --strategy stack --repos repos.txt

# Aplicar + commit + push (abre branches em cada repo para PR)
bash scripts/propagate-agents-md.sh --strategy stack --repos repos.txt --commit --push
```

Estratégias disponíveis: `pointer` (referência), `full` (cópia integral),
`stack` (Parte I por referência + Parte II local copiada do template da stack).

---

> **Fim do AGENTS.md.** Para o template de relatório de execução, ver
> [docs/ai-agents/response-template.md](docs/ai-agents/response-template.md).
> Para o checklist pré-implementação, ver
> [docs/ai-agents/pre-flight-checklist.md](docs/ai-agents/pre-flight-checklist.md).
