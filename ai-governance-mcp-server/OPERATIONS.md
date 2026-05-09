# Operations Runbook — ai-governance-mcp-server

> Guia operacional para colocar e manter o MCP em uso no time. Complementa o
> [README.md](README.md) (foco em desenvolvimento) e os [ADRs](docs/decisions/)
> (foco em decisões arquiteturais).

---

## 1. Pré-requisitos

| Componente | Mínimo | Testado em |
|---|---|---|
| Python | 3.11 | 3.12.10 |
| pip | 24.x | 25.0.1 |
| git | 2.x | 2.40+ |
| GitHub CLI (`gh`) | apenas para PR validate workflow + abertura de PR | 2.x |
| Docker (host) | 20.10+ (suporta Buildx) | 28.3.0 |

### OS suportados

| OS | Status | Nota |
|---|---|---|
| **Ubuntu 20.04 LTS** | ✅ produção (VMs cloud do `dataforalltech`) | Docker 20.10+ via apt; container roda debian-slim internamente — nenhum ajuste necessário |
| Ubuntu 22.04 / 24.04 | ✅ esperado funcionar | mesma stack |
| macOS (Intel + Apple Silicon) | ✅ desenvolvimento | Docker Desktop; imagem multi-arch publicada cobre arm64 quando disponível |
| Windows + WSL2 | ✅ desenvolvimento (testado) | Docker Desktop com WSL2 backend; ver §5.4 |
| Windows nativo | ⚠️ não testado | Use WSL2 |
| Linux air-gapped | ⚠️ fallback manual | §6.3 (sem Docker) |

> **Observação Ubuntu 20.04**: glibc 2.31 do host não é problema — o container
> debian-bookworm-slim tem sua própria libc. Apenas confirme que o Docker
> instalado é >= 20.10 (suporta Buildx). Em distros antigas, `apt install
> docker.io` pode entregar versão mais velha — preferir o repo oficial Docker.

---

## 2. Instalação

### 2.1 Clone + editable install

```bash
git clone <url>/dataforalltech/platform-service-template.git
cd platform-service-template/ai-governance-mcp-server
pip install -e ".[dev]"
```

Após o `pip install -e .`, o entry point `ai-governance-mcp-server` fica disponível no PATH.

### 2.2 Verificação rápida

```bash
# Smoke test (spawn local + chama as 24 tools via stdio)
python scripts/smoke_test.py
# Expected: "smoke result: 21/21 ok" (submit_suggestion e create_adr são pulados)

# Validação estrutural do ecosystem.yaml
python -c "from src.knowledge.ecosystem_graph import EcosystemGraph; from pathlib import Path; \
  print(EcosystemGraph(Path('knowledge-base/ecosystem.yaml')).stats())"
```

### 2.3 Registro nos clients MCP

Ver [README.md → Conectando agentes ao MCP](README.md). Resumo:

| Client | Comando |
|---|---|
| Claude Code (CLI) | `claude mcp add -s user ai-governance "$(which ai-governance-mcp-server)"` |
| Claude Desktop | Editar `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\`, macOS: `~/Library/Application Support/Claude/`) |

**Restart obrigatório do client** após mudança de config.

---

## 3. Configuração

Variáveis (todas opcionais — defaults seguros):

| Variável | Default | Função |
|---|---|---|
| `GOVERNANCE_KB_PATH` | `<projeto>/knowledge-base` | Pasta com markdowns + ecosystem.yaml |
| `GOVERNANCE_SUGGESTIONS_PATH` | `<kb>/suggestions/` | Store de sugestões cross-repo |
| `GOVERNANCE_LOG_LEVEL` | `INFO` | DEBUG \| INFO \| WARNING \| ERROR |
| `GOVERNANCE_LOG_FORMAT` | `json` | json \| text |
| `GOVERNANCE_SEARCH_MAX_LIMIT` | `20` | Teto de hits por busca |
| `GOVERNANCE_SEARCH_DEFAULT_LIMIT` | `5` | Default sem `limit` |
| `GOVERNANCE_SEARCH_SNIPPET_LENGTH` | `400` | Tamanho do trecho retornado |

`.env.example` na raiz documenta todas.

---

## 4. Operação rotineira

### 4.1 Atualizando o `ecosystem.yaml`

1. Editar `knowledge-base/ecosystem.yaml` (PR review obrigatório).
2. Validar localmente: `python scripts/scan_ecosystem.py` — exit 0 esperado.
3. CI roda `graph-validation` automaticamente em PR.

Convenções:

- Nodes: `kind ∈ {repository, service, library, contract, team, port}`.
- Edges: `relation ∈ {depends_on, consumes, produces, owns, deprecated_by, replaces, runs_on_port, uses_lib, provides_api, consumes_event, produces_event, based_on}`.
- Aliases (`aliases: [...]` em node) para preservar nomes legacy quando renomear canônico.

### 4.2 Detectando drift (semanal/mensal)

```bash
python scripts/scan_ecosystem.py --path /caminho/para/repos --format json --output drift.json
```

Triagem do drift exige decisão humana caso a caso:

- **Conflito de porta**: `ecosystem.yaml` desatualizado **ou** `.env` legacy do repo está errado. Decidir qual é a verdade canônica e ajustar.
- **Repo no disco mas não no YAML**: serviço novo? adicionar ao YAML.
- **Serviço no YAML mas não no disco**: deprecated não-marcado? adicionar `deprecated_by`. Repo movido? atualizar path.
- **Lib drift**: `pyproject.toml` do repo evoluiu além do que o YAML modela. Atualizar edges `uses_lib`.

### 4.3 Atualizando políticas textuais

Editar arquivos em `knowledge-base/*.md` (frontend.md, backend.md, etc.). Reload é automático no próximo spawn do MCP — não precisa restart manual de cada client além do já necessário para mudança de código.

### 4.4 Adicionando uma nova tool MCP

1. `src/tools/<nome>_tool.py` — função pura `(repo, **kwargs) -> dict`.
2. Exportar em `src/tools/__init__.py`.
3. Registrar schema + dispatch em `src/server/mcp_server.py`.
4. Adicionar caso em `scripts/smoke_test.py`.
5. Testes em `tests/test_<nome>.py`.
6. Atualizar `README.md` (tabela de tools) e `CHANGELOG.md`.

### 4.5 Triando sugestões cross-repo

Sugestões persistem em `<kb>/suggestions/<id>.json`. Workflow:

```bash
# Ver pendentes
echo '{"target_repo":"platform-cdc","status":"pending"}' | <invocar list_suggestions>

# Aceitar/rejeitar via update_suggestion_status (id, new_status, note, by)
```

Status flow esperado: `pending → acknowledged → accepted/rejected → done`.

---

## 5. Troubleshooting

### 5.1 "Tools não aparecem na sessão Claude"

| Sintoma | Causa | Fix |
|---|---|---|
| Sessão Claude Code não vê 24 tools | MCP carregado no spawn da sessão; mudança de config exige restart | `claude mcp list` → confirma registro; abrir nova sessão |
| Claude Desktop não vê | Config alterada sem restart total do app (system tray) | Quit completo via tray + reopen |

### 5.2 "MCP server falhou ao subir"

Logs do client capturam stderr do MCP. Caminhos:

- Claude Desktop (Windows): `%APPDATA%\Claude\logs\mcp-server-ai-governance.log`
- Claude Code: stderr da sessão

Erros comuns:

| Mensagem | Causa | Fix |
|---|---|---|
| `ecosystem.yaml não encontrado` | `GOVERNANCE_KB_PATH` aponta para path inexistente | Verificar path + permissões de leitura |
| `node duplicado: 'X'` | Edição manual quebrou unicidade do YAML | `git diff knowledge-base/ecosystem.yaml` + corrigir |
| `node sem id válido` | Linha YAML mal formada | Validar com `yamllint` |
| `ImportError: No module named 'mcp'` | Pacote não instalado no Python que o entry point usa | `pip install -e .` no Python correto |

### 5.3 "Validator dá falso positivo"

Conhecidos (em ADR-0004):

- Strings literais com palavras-chave (`pyproject.toml`, `fallback`) — refinada a regex `_DEPENDENCY_PATTERNS` em commit `71151f8`.

Para reportar novos: abrir issue ou usar `submit_suggestion` no próprio MCP com `target_repo=ai-governance-mcp-server`.

### 5.4 Notas Windows-específicas

- **stdout em cp1252**: caracteres unicode em prints podem quebrar. Resolve com `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` (já setado em scripts críticos).
- **Linhas CRLF**: `core.autocrlf=true` no git é tolerado; ruff/pytest lidam transparentemente.
- **Caminho do `.exe`**: `C:\Users\<user>\AppData\Local\Programs\Python\Python312\Scripts\ai-governance-mcp-server.exe`.

### 5.5 "PR validate workflow falha sempre"

`continue-on-error: true` por design — informativo, não bloqueia merge enquanto validator está em calibração. Quando confiar: editar `.github/workflows/pr-validate.yml` removendo a flag.

### 5.6 "Pre-commit hook lento"

Cada invocação spawna processo MCP novo (~150ms). Para commits frequentes:

- Comente o hook temporariamente (`mv .git/hooks/pre-commit{,.disabled}`).
- Ou use `git commit --no-verify` **somente** se confiante (defeats the purpose).
- Otimização futura: hook persistente que mantém MCP rodando entre commits (não implementado).

---

## 6. Deploy / atualização

### 6.1 Atualizando o servidor

```bash
cd ai-governance-mcp-server
git pull
pip install -e ".[dev]"
# Restart de TODAS as sessões Claude Code/Desktop ativas
```

### 6.2 Distribuição via Docker (recomendado)

A imagem oficial vive em `d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server` — mesmo ACR usado por todos os serviços da plataforma. Tags:

- `:0.1.0` (release patch específico)
- `:0.1` (último patch da minor 0.1)
- `:latest` (último release estável)
- `:0.1.0-rc1` etc. (pré-releases — não viram `:latest`)

#### Modelo de release (CI builda, humano empurra)

O CI (`ai-governance-mcp-release.yml`) **constrói a imagem mas não empurra para o ACR** — salva como GitHub Actions artifact (.tar.gz, retenção 90 dias). O operador puxa o artifact e empurra para o ACR de uma máquina com acesso. Esse fluxo:

- **Não exige credenciais ACR no GitHub**.
- Funciona com Network ACL restritivo no ACR.
- Mantém build reprodutível e auditável em runner determinístico.
- Centraliza o controle de push no humano (auditável via `docker push` log).

Trigger:

```bash
# Por tag git (canônico)
git tag ai-governance-mcp/v0.1.0
git push origin ai-governance-mcp/v0.1.0

# Ou manualmente sem tag
gh workflow run ai-governance-mcp-release.yml -f tag=0.1.0
```

CI roda em ~3-5 min e emite no Step Summary as instruções de pull abaixo (mesmas para qualquer release).

#### Pull do artifact + push para ACR

Em uma máquina com `gh` CLI logado **e** acesso ao ACR:

```bash
# Variáveis (ajuste a versão)
VERSION=0.1.0
SLUG=$(echo "$VERSION" | tr '/+' '__')
RUN_ID=$(gh run list --workflow=ai-governance-mcp-release.yml --limit 1 \
    --json databaseId --jq '.[0].databaseId')

# 1. Baixe o artifact da run mais recente
gh run download $RUN_ID \
    --repo dataforalltech/platform-service-template \
    --name "ai-governance-mcp-server-$SLUG" \
    --dir /tmp/

# 2. Carregue no Docker local
gunzip -c /tmp/ai-governance-mcp-server.tar.gz | docker load

# 3. Login no ACR (suas credenciais locais)
docker login d4all.azurecr.io
# OU: az acr login --name d4all  (preferível se você tem az CLI)

# 4. Re-tag e push
LOCAL=ai-governance-mcp-server:$VERSION
REMOTE_BASE=d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server

docker tag $LOCAL $REMOTE_BASE:$VERSION
docker push $REMOTE_BASE:$VERSION

# 5. Tags adicionais para releases estáveis (X.Y.Z, sem -rc, -beta etc.)
docker tag $LOCAL $REMOTE_BASE:0.1
docker tag $LOCAL $REMOTE_BASE:latest
docker push $REMOTE_BASE:0.1
docker push $REMOTE_BASE:latest
```

#### Pull manual (uso por consumidores)

Após push, qualquer dev/agente puxa normalmente:

```bash
docker pull d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0
```

#### Configuração do client

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json` no Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` no macOS):

```json
{
  "mcpServers": {
    "ai-governance": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/abs/path/to/local/suggestions:/app/knowledge-base/suggestions",
        "d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0"
      ]
    }
  }
}
```

**Claude Code (CLI)**:

```bash
claude mcp add -s user ai-governance -- docker run -i --rm \
  -v /abs/path/to/local/suggestions:/app/knowledge-base/suggestions \
  d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0
```

Notas:

- O flag `-i` (`--interactive`) é obrigatório — MCP usa stdio.
- `--rm` evita lixo de containers parados.
- O volume mount em `/app/knowledge-base/suggestions` é **obrigatório** se você quer que sugestões persistam entre sessões. Sem ele, o store é efêmero.
- A knowledge-base textual + ecosystem.yaml são embutidos na imagem na release. Para customizar localmente, monte sua própria pasta em `/app/knowledge-base` (ler todo) e o servidor usa essa.

#### Cold start

~600-800ms a mais que invocação direta de Python (overhead de spawn de container). Aceitável: cada sessão MCP spawna 1x.

#### Atualização

```bash
docker pull d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1
# Reiniciar TODAS as sessões Claude Code/Desktop ativas (next run usa imagem nova).
```

#### Build local (para dev / hotfix sem release)

```bash
cd ai-governance-mcp-server
docker build -t ai-governance-mcp-server:dev .
docker compose run --rm mcp python -c "print('OK')"
```

`docker-compose.yml` está incluído para conveniência de dev.

### 6.3 Distribuição manual (fallback)

Quando Docker não é viável (políticas locais, ambiente air-gapped, etc.):

1. Cada dev: `git clone` + `pip install -e .` em path conhecido.
2. Registrar no client com path absoluto do entry point `.exe` / binário.
3. Aceitar fragilidade — config quebra se o projeto mover.

Detalhes na §2 deste runbook.

### 6.4 Pacote pip privado (futuro — não implementado)

Quando rolar:

1. Build: `python -m build` produz `dist/ai_governance_mcp_server-0.1.0-py3-none-any.whl`.
2. Push para Artifactory / Azure Artifacts / similar.
3. Devs: `pip install ai-governance-mcp-server`.

Vale priorizar quando: Docker virar fricção em algum subset do time (ex.: integrações pesadas com IDE que não rodam containers fácil).

### 6.3 Versionamento

SemVer aplicado ao `version` em `pyproject.toml` + tag git:

- `0.1.x` — patches (bugfix, doc, refactor sem mudança de schema)
- `0.x.0` — minor (novas tools, novos campos opcionais em payload)
- `x.0.0` — major (mudança breaking de schema MCP — exige plano de migração)

`CHANGELOG.md` é a fonte de verdade da história entre tags.

---

## 7. Rollback

### 7.1 Reverter código

```bash
git revert <sha>           # cria commit reverso (preferível)
# OU em emergência:
git reset --hard <sha-bom>  # destrutivo, exige push --force se já publicado
```

Após revert, devs precisam `git pull && pip install -e .` para o entry point apontar para o código antigo.

### 7.2 Reverter ecosystem.yaml

```bash
git log knowledge-base/ecosystem.yaml
git checkout <sha-bom> -- knowledge-base/ecosystem.yaml
git commit -m "revert(graph): rollback ecosystem.yaml para <sha-bom>"
```

### 7.3 Sugestões

`<kb>/suggestions/` é git-trackeada por padrão (audit trail). Para desfazer uma update_status incorreta: `git checkout <sha> -- knowledge-base/suggestions/<id>.json`.

---

## 8. Métricas / observabilidade

### 8.1 Logs estruturados

Servidor emite JSON em stderr a cada chamada:

```json
{"ts":"...","level":"INFO","logger":"__main__","message":"tool_called",
 "extras":{"tool":"validate_agent_decision","args_keys":["..."]}}
```

Coletar com qualquer pipeline JSON-ingest (Loki, ELK, Datadog).

### 8.2 Métricas úteis (não implementado, sugestão)

| Métrica | Como derivar dos logs | Por quê |
|---|---|---|
| `tool_calls_total{tool=}` | count de `message="tool_called"` por tool | Identifica tools mais usadas |
| `validate_decision_blocked_total` | count de respostas com `approved=false` | Frequência de decisões reprovadas |
| `suggestion_created_total{target_repo=}` | count de `message="suggestion_created"` | Demanda por melhorias por repo |

Dashboard sugerido fica para fase 2 (post-launch).

---

## 9. Limites conhecidos / não-objetivos

- **Não escala para >5k sugestões** (file-per-suggestion). Migração para SQLite documentada em ADR-0003.
- **Não escala para >200 nodes** no grafo (networkx in-memory). Migração para Neo4j em ADR-0002.
- **Sem auth no transporte stdio** — assume cliente local confiável. Para HTTP futuro, exige design de auth (não implementado).
- **Validator regex tem falsos positivos conhecidos** — refinamentos pendentes listados em ADR-0004.

---

## 10. Contato

| Tipo | Canal |
|---|---|
| Bug | `submit_suggestion` no MCP com `target_repo=ai-governance-mcp-server` ou GitHub issue |
| Mudança de política | PR direto em `knowledge-base/*.md` com review humano |
| Mudança de lib privada (`platform-*-lib`) | LIB CHANGE REQUEST aprovado por @caiog (§18 AGENTS.md) |
| Drift do ecossistema | Output de `scripts/scan_ecosystem.py` em PR |
