# ADR 0002 — Grafo do ecossistema in-memory com networkx

**Data**: 2026-05-05
**Status**: Aceito
**Decisor**: @caiog (review humano)
**Implementação**: commit `19b2a44`

## Contexto

Política textual (markdown na knowledge-base) cobre regras gerais mas não responde "quem consome o quê", "qual o canônico de X", "quais portas estão alocadas". Precisávamos modelar relações estruturais entre 22 serviços, 4 libs privadas, 22 portas e 20 contratos.

Opções avaliadas:

1. **In-memory `networkx.MultiDiGraph` carregado de YAML.**
2. Banco de grafos (Neo4j, Memgraph) com Cypher.
3. SQL com tabelas + JOINs.
4. RDF/triple store (rdflib, Apache Jena).

## Decisão

**Opção 1**: `networkx>=3.2`, fonte declarativa em `knowledge-base/ecosystem.yaml`, validação estrutural no boot.

## Consequências

### Positivas

- **Zero serviço externo** — alinhado com o briefing original ("não use serviços externos obrigatórios").
- **YAML é editável por humano** com revisão via PR. Cada mudança no grafo é uma linha de diff.
- **Carregamento atômico** — o `EcosystemGraph._load()` valida tudo no boot (kinds desconhecidos, relações desconhecidas, arestas com endpoint inexistente, nós duplicados). Se algo está errado, o servidor avisa imediatamente em log, não devolve resultado errado depois.
- **API pública estável** — as 4 tools (`query_ecosystem_graph`, `find_consumers_of`, `find_dependencies_of`, `get_service_metadata`) chamam métodos do `EcosystemGraph`. A camada de tools nunca toca em `networkx` direto. Trocar para Neo4j é refatorar uma única classe.
- **Performance** — 73 nós, 166 arestas. Queries em <1ms. Suporta com folga até 5–10× isso sem problemas.

### Negativas

- **Não escala para milhares de nós** — networkx é Python puro, queries em árvore com BFS limitada. Aceitável para um ecossistema interno; se virarmos modelagem de toda a infra (Kubernetes pods, etc.), troca-se a engine.
- **Sem queries declarativas** — sem Cypher, sem SPARQL. Tudo é código Python na classe `EcosystemGraph`. Para queries complexas (caminhos com filtros, padrões de subgrafo), o código fica verboso.
- **YAML é manual** — drift entre código real e o seed é possível. Mitigado pelo `scripts/scan_ecosystem.py` (ADR-0004) que reporta drift.

## Alternativas rejeitadas

### Neo4j / Memgraph

- Dá Cypher, performance e bibliotecas para análise de grafos. Mas:
- Adiciona container/serviço externo no docker-compose de qualquer agente que rode o MCP.
- Tornar persistente complica deployment.
- Vale revisitar quando: (a) >200 nós, (b) precisarmos de queries pattern-matching reais, (c) tivermos múltiplos consumidores precisando do mesmo grafo.

### SQL com JOINs

- Modelagem de grafo em SQL é desconfortável (JOINs recursivos para travessia). Ganho zero sobre networkx em escala atual.

### RDF/triple store

- Riqueza semântica não compensa o overhead de aprender vocabulário SPARQL.

## Migração futura para Neo4j

Quando rolar:

1. Subir Neo4j via docker-compose (com perfil ou flag opcional).
2. Reescrever `src/knowledge/ecosystem_graph.py::EcosystemGraph` para falar com o driver Neo4j.
3. Mapear cada operação atual: `list_nodes`, `neighbors`, `find_consumers_of`, `find_dependencies_of`, `shortest_path`, `stats`.
4. Manter a interface pública idêntica — tools não mudam.
5. Manter o YAML como fonte declarativa: gerar comandos `CREATE` no boot ou via script de seed.

## Referências

- [knowledge-base/ecosystem.yaml](../../knowledge-base/ecosystem.yaml)
- [src/knowledge/ecosystem_graph.py](../../src/knowledge/ecosystem_graph.py)
- AGENTS.md §47 (portas) e §49 (responsabilidades) — fonte canônica do seed
