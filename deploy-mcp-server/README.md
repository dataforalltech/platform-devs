# deploy-mcp-server

Sidecar MCP para operações Git/PR, consulta e build direto no ACR, workspace
local e leitura do ledger tenant-scoped. O acesso HTTP ocorre somente pelo MCP
Gateway, com Twin Token e política por tool.

## Decisão de entrega

GitHub Actions foi aposentado em 2026-07-15. Esta aplicação:

- não cria arquivos em `.github/workflows/`;
- não dispara, consulta ou cancela workflow runs;
- não propaga secrets/variables de Actions;
- não executa deploy por workflow;
- não considera o ledger como prova de execução de CI/CD.

As tools de baixo nível do cliente antigo falham de forma fechada e não são
publicadas no catálogo MCP. O ledger de workflows permanece somente para leitura
do histórico anterior à decisão.

## Tools ativas

| Grupo | Tools |
|---|---|
| Git | `list_repos`, `create_branch`, `list_branches`, `commit_files` |
| Pull request | `create_pr`, `get_pr`, `merge_pr`, `list_prs` |
| ACR | `acr_build`, `list_acr_images` |
| Workspace | `get_repos_root`, `set_repos_root`, `list_local_repos`, `clone_repo` |
| Ledger read-only | `list_deployments`, `get_deployment`, `list_deploy_events`, `list_pr_history`, `list_workflow_history`, `list_registered_repos` |

`acr_build` altera estado quando `push=true`. Ele não cria `latest` e informa
explicitamente que SBOM, provenance e scan continuam pendentes; portanto, seu
retorno isolado não comprova conformidade de supply chain.

## O que executa CI/CD agora

Nenhum executor central substituto foi comprovado neste workspace. O
`pipeline-mcp-server` registra gates, aprovações, promoções e histórico, mas não
executa testes, build ou deploy. Até a escolha de um executor, siga o fluxo manual
controlado em `platform-infra/docs/architecture/delivery-without-github-actions.md`.

Build/push e deploy Swarm exigem autorização humana. Para a plataforma, prefira
os scripts e runbooks canônicos do `platform-infra`; não trate esta sidecar como
atalho para contornar aprovações.

## Configuração

Use `.env.example` como inventário de nomes. Nunca registre valores de segredo.

| Variável | Uso |
|---|---|
| `DEPLOY_GITHUB_TOKEN` | Git e pull requests |
| `DEPLOY_GITHUB_ORG` | Organização padrão |
| `DEPLOY_ACR_REGISTRY` | Registry ACR |
| `DEPLOY_ACR_NAMESPACE` | Namespace de imagens |
| `DEPLOY_ACR_USERNAME` / `DEPLOY_ACR_PASSWORD` | Consulta e push ACR; não são propagados ao GitHub |
| `MCP_TWIN_AUDIENCE` | Audiência do inner token |
| `URL_ADMIN_TWIN_JWKS` | JWKS para validação do token |
| `MCP_PORT` | Porta HTTP interna |

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
python -m src.server.mcp_server
```

No PowerShell, ative com `.venv\Scripts\Activate.ps1`.

## Validação da retirada de Actions

```bash
pytest -q tests/test_no_github_actions.py tests/test_acr.py tests/test_mcp_server.py
```

O gate transversal também deve ser executado no `platform-infra`:

```bash
python scripts/validate_no_github_actions.py --repo platform-devs
```

## Limites operacionais

- Não há deploy automático comprovado.
- `acr_build(push=true)` e operações Git/PR produzem efeito externo.
- O box HML não é atualizado por commit; a cópia para
  `/opt/dataforall/deploy` é um passo manual separado.
- Kubernetes é experimental; Docker Swarm é o runtime oficial.
