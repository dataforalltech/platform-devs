# AGENTS.md — Política para Agentes de IA

> Diretrizes para agentes de IA que atuam neste repositório.
> Leia este arquivo ANTES de qualquer ação.

## Regras Gerais

1. **Leia antes de agir** — leia os arquivos relevantes antes de modificar qualquer coisa
2. **Prefira edições cirúrgicas** — não reescreva arquivos inteiros sem necessidade
3. **Respeite os padrões** — siga os padrões estabelecidos no código existente
4. **Não altere dependências** sem aprovação explícita do owner
5. **Testes obrigatórios** — toda mudança funcional deve vir com testes
6. **Commits atômicos** — cada commit deve ter uma única responsabilidade clara

## Arquitetura

Descreva a arquitetura do serviço aqui. Inclua:
- Componentes principais e suas responsabilidades
- Fluxo de dados entre componentes
- Dependências externas (bancos, APIs, serviços)
- Decisões arquiteturais relevantes (ver `docs/decisions/`)

## Padrões de Código

- **Linguagem:** Python 3.12+
- **Formatter:** ruff (configurado em `pyproject.toml`)
- **Type checker:** mypy
- **Testes:** pytest com cobertura mínima de 80%
- **Estilo:** PEP 8, type hints obrigatórios em funções públicas
- **Docstrings:** Google style para funções e classes públicas

## Arquivos Críticos (não modificar sem aprovação)

- `src/config/settings.py` — configurações de ambiente
- `pyproject.toml` — dependências e configurações do projeto
- `.github/workflows/` — pipelines de CI/CD
- `alembic/` — migrações de banco de dados (se existir)

## Fluxo de Trabalho

1. Crie branch a partir de `develop`: `git checkout -b feat/minha-feature develop`
2. Implemente com testes unitários e de integração
3. Execute `ruff check .` e corrija todos os problemas
4. Execute `pytest` e garanta cobertura >= 80%
5. Abra PR para `develop` com descrição clara das mudanças
6. Aguarde review do owner antes de fazer merge

## Convenções de Commit

Seguimos [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` nova funcionalidade
- `fix:` correção de bug
- `docs:` documentação
- `refactor:` refatoração sem mudança de comportamento
- `test:` adição ou correção de testes
- `chore:` tarefas de manutenção

## Contato

Owner: @{{owner}}
Canal de suporte: #{{slack_channel}}
