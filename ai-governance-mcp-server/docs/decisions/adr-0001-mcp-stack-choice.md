# ADR 0001 — Escolha do stack do servidor MCP

**Data**: 2026-05-05
**Status**: Aceito
**Decisor**: @caiog (review humano)
**Implementação**: commit `19b2a44`

## Contexto

Precisávamos de um servidor MCP que agentes de IA (Claude Code, Claude Desktop, Cursor, agentes via SDK) possam consultar antes de implementar mudanças em qualquer um dos ~35 repos do ecossistema `dataforalltech`. O servidor expõe diretrizes textuais, política de fallback, validação de decisão, mapa do ecossistema e canal de sugestões cross-repo.

Opções avaliadas:

1. **Python + SDK oficial `mcp` + transporte stdio.**
2. Node/TypeScript + `@modelcontextprotocol/sdk` + stdio.
3. Servidor HTTP (FastAPI/express) expondo endpoints REST com adapter MCP em cima.
4. Serviço gerenciado externo (Anthropic Claude API com tool definitions).

## Decisão

**Opção 1**: Python + SDK oficial `mcp>=1.2.0` + transporte stdio.

## Consequências

### Positivas

- **Stack idêntica ao resto do ecossistema** — a maioria dos serviços do `dataforalltech` é Python/FastAPI; agentes que tocam neles já conhecem este idioma. Sem fricção de aprender Node/TypeScript.
- **stdio é o transporte mais simples e mais suportado por clientes MCP** (Claude Code, Claude Desktop, Cursor, SDK). Sem porta de rede, sem auth, sem firewall — o cliente spawna o processo e fala via stdin/stdout.
- **Pydantic 2 + tipagem forte** alinhado com `pydantic-settings` que já usamos em todos os serviços derivados do template Python.
- **Sem dependência de runtime externo** — servidor é spawned por chamada do cliente; não há daemon.
- **Auditoria de chamadas via logs JSON em stderr** — o MCP usa stdout para o protocolo; sobra stderr para observabilidade.

### Negativas

- **Cold-start a cada sessão** — toda vez que um cliente conecta, paga-se ~150ms de import + carregamento da KB e do grafo. Aceitável para o volume atual (poucas chamadas por sessão).
- **Sem multi-tenancy** — um processo MCP atende um cliente por vez. Para escalar, eventualmente precisamos de transporte HTTP/SSE.
- **Logs duplicados em multi-cliente** — cada cliente spawna seu processo, logs vão para stderr local. Centralizar exige redirecionar para Loki/ELK no orquestrador.

## Alternativas rejeitadas

### Node/TypeScript

- O SDK MCP em TS é maduro, mas a maioria dos consumidores aqui é Python.
- Nem o validador, nem o grafo, nem o store de sugestões precisam de async I/O pesado — Python lida bem.

### HTTP/REST com adapter MCP

- Adiciona complexidade (auth, deploy, escalonamento) sem ganho proporcional na fase atual.
- Vale revisitar **quando** quisermos múltiplos consumidores compartilhando estado mutável (sugestões) sem race conditions de filesystem.

### Serviço gerenciado (Anthropic API)

- Acoplaria o ecossistema a um vendor.
- Não cobre tools customizadas com persistência local (sugestões, scanner).

## Referências

- [README do projeto](../../README.md)
- AGENTS.md §17 (mapa de bibliotecas privadas)
- pyproject.toml — `dependencies`
