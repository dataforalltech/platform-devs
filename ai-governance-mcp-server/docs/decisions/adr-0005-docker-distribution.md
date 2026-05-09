# ADR 0005 — Distribuição via imagem Docker (stdio-via-docker-run)

**Data**: 2026-05-06
**Status**: Aceito
**Decisor**: @caiog
**Implementação**: commit `<próximo>`

## Contexto

Para uso em produção pelo time inteiro do `dataforalltech`, o MCP server precisa de um mecanismo de distribuição que substitua o atual `git clone + pip install -e .` (frágil, manual, depende de versão certa de Python no host).

Opções avaliadas:

1. **Imagem Docker invocada via `docker run -i --rm`** — cliente MCP spawna container por sessão.
2. **Pacote pip privado** (Artifactory / Azure Artifacts / etc.) instalado com `pip install ai-governance-mcp-server`.
3. **Servidor HTTP/SSE** rodando como daemon containerizado, clientes conectam via URL.
4. **Continuar manual** com runbook claro.

## Decisão

**Opção 1**: Docker image em `d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server`, invocada por `docker run -i --rm` per sessão MCP.

## Consequências

### Positivas

- **Zero setup de Python no host** — o usuário só precisa de Docker (que a maioria já tem).
- **Versão pinada da release** — imagem `:0.1.0` é imutável; `:latest` segue stable. Sem drift entre máquinas.
- **Knowledge-base + ecosystem.yaml embutidos** — política e topologia versionadas com a release. Volume mount externo ainda suportado para customização local.
- **Multi-arch** (amd64 + arm64) via Buildx — devs com Mac M-series não têm fricção.
- **Funciona com transporte stdio nativo do MCP** — sem refactor de código (alinhado com ADR-0001).
- **SBOM + provenance** assinados via Buildx — supply chain auditável.
- **Atualização triviial**: `docker pull X:0.1` + restart do client.

### Negativas

- **Cold start adicional** — spawn de container custa ~600-800ms vs ~150ms de invocação Python direta. Aceitável: cada sessão MCP spawna 1x; tools individuais não pagam essa latência.
- **Volume mount obrigatório para sugestões** — se o usuário esquecer o `-v`, sugestões viram efêmeras. Documentado no Dockerfile e OPERATIONS, mas é pegadinha real.
- **Dependência de Docker no host** — em ambientes air-gapped ou sem privilégio de container, fallback manual ainda é necessário (§6.3 OPERATIONS).
- **Não escala para múltiplos clientes simultâneos compartilhando estado** — cada container tem seu filesystem efêmero. Suggestions só compartilham via volume mount em path comum. Para múltiplas máquinas, exigirá NFS/S3 (não nessa fase).

### Trade-off principal

Escolhemos **Opção 1** sobre Opção 2 (pip privado) porque:

- Nem todo dev tem Python 3.12 (Docker abstrai versão).
- Pip privado adiciona dependência de Artifactory/Azure (vendor lock).
- Docker já é a stack de distribuição padrão do `dataforalltech`.

Escolhemos **Opção 1** sobre Opção 3 (HTTP daemon) porque:

- HTTP transport exige refactor da camada de transporte (mcp SDK suporta mas é trabalho).
- HTTP exige design de auth e CORS (não-trivial).
- Cada agente já tem expectativa de "MCP local" — daemon centralizado vira ponto de falha único.

## Alternativas rejeitadas

### Opção 2 — Pip privado

- Mais simples para devs Python; quebra para devs IDE-heavy.
- Vendor lock para Artifactory/Azure.
- Pendente: pode coexistir com Docker no futuro como canal alternativo (§6.4 OPERATIONS).

### Opção 3 — HTTP daemon

- Resolve multi-tenancy real, mas custo de implementação alto.
- Vale revisitar quando: (a) >5 agentes simultâneos compartilhando sugestões, (b) precisarmos de auth fora do trust local.

### Opção 4 — Continuar manual

- Frágil (path absoluto, versão de Python). Inadequado para produção.

## Validação

- CI workflow `ai-governance-mcp release` constrói a imagem (linux/amd64) e a publica como GitHub Actions **artifact** (`.tar.gz`, retenção 90 dias) — sem empurrar para registry.
- Imagem inicial `:0.1.0` é gerada após primeira tag `ai-governance-mcp/v0.1.0`; operador faz pull do artifact e empurra ao ACR (`d4all.azurecr.io`) localmente.
- Métrica de adoção: # de devs configurados no Docker config / total = >80% após 4 semanas.

## Modelo de release (revisão pós-incidente)

A versão inicial deste ADR previa push direto do CI para o ACR. Na primeira tentativa de release v0.1.0, esbarramos em barreira de autenticação — credenciais válidas localmente não autenticavam do runner GitHub-hosted, sintoma típico de Network ACL ou de SP com escopo restrito que não inclui hosts externos.

A solução adotada **separa build (CI, automatizado) de push (humano, local)**:

- CI gera `.tar.gz` com `docker build --output type=docker,dest=...` e publica como artifact.
- Operador puxa o artifact (`gh run download`), faz `docker load`, re-tagga e `docker push` para o ACR de uma máquina autorizada.
- Workflow CI não precisa mais de `ACR_USERNAME` / `ACR_PASSWORD`.

Ganhos:

- Funciona com qualquer política de rede do ACR (privado, ACL, Private Link).
- Sem credenciais Azure no GitHub Actions secrets.
- Push controlado por humano = auditoria mais clara via `docker push` log.

Custo:

- ~2 min de passo manual a cada release (versus push automatizado).
- Operador precisa ter `gh` CLI logado + acesso ao ACR.

Esse trade-off é aceitável enquanto cadência de release for baixa (semanal ou menor). Quando virar diária/contínua, considerar:

1. Self-hosted runner em rede que tem acesso ao ACR (resolve auth + push em CI).
2. OIDC federation entre GitHub e Azure AD (`azure/login@v2` com workload identity, sem secrets).

## Compatibilidade de host OS

Imagem é debian-bookworm-slim com Python 3.12 (independente do host). Hosts
testados/suportados:

- **Ubuntu 20.04 LTS** (canônico das VMs cloud do `dataforalltech`) — requer
  Docker >= 20.10. glibc 2.31 do host não impacta porque o container traz a
  própria libc.
- Ubuntu 22.04 / 24.04 — esperado funcionar sem ajustes.
- macOS Intel + Apple Silicon (Docker Desktop) — multi-arch quando o build
  incluir arm64.
- Windows + WSL2 — desenvolvimento testado.

Matriz completa em `OPERATIONS.md §1`.

## Referências

- [Dockerfile](../../Dockerfile)
- [.github/workflows/ai-governance-mcp-release.yml](../../../.github/workflows/ai-governance-mcp-release.yml)
- [OPERATIONS.md §6.2](../../OPERATIONS.md#62-distribuição-via-docker-recomendado)
- ADR-0001 (escolha de transporte stdio)
