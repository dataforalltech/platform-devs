# AGENTS.md — política operacional do serviço

## Regras obrigatórias

1. Confirme comportamento no código, Compose e runbooks antes de afirmar.
2. Não registre valores de segredo; use apenas nomes e referências ao Vault.
3. GitHub Actions é proibido. Não crie `.github/workflows/`, não dispare runs e
   não armazene credenciais em secrets/variables de Actions.
4. Docker Swarm é o runtime oficial; Kubernetes é experimental.
5. Mudança funcional exige testes e evidência vinculada ao commit.
6. Build/push, deploy, escala, rollback, seed e migration exigem autorização.
7. `pipeline-mcp` registra estado e aprovações, mas não prova que gates rodaram.

## Arquivos críticos

- `src/config/settings.py` — contrato de configuração;
- `pyproject.toml` — dependências e toolchain;
- `Dockerfile` e Compose/stack — build e runtime;
- `alembic/` ou diretório equivalente — migrations;
- `docs/platform/` — perfil, conformidade e histórico append-only.

## Fluxo de trabalho

1. Crie branch a partir da base definida pelo repositório.
2. Implemente testes unitários, integração e contrato aplicáveis.
3. Execute localmente lint, tipos, testes, cobertura, secret scan, SAST e SCA.
4. Registre comandos, versões, resultados e commit no histórico de conformidade.
5. Abra PR e obtenha revisão do owner.
6. Para release, siga o runbook manual controlado até existir executor aprovado.

## Convenções

Use Conventional Commits e preserve a língua/estilo já adotados pelo projeto.
Owner: `{{owner}}`. Canal: `#{{slack_channel}}`.
