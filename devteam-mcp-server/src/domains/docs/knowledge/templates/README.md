# {{service_name}}

> {{description}}

## Installation

```bash
pip install {{service_name}}
# ou
docker pull {{registry}}/{{service_name}}:latest
```

## Usage

```python
# exemplo de uso mínimo
from {{service_name}} import Client

client = Client()
result = client.run()
print(result)
```

## Configuration

| Variável | Descrição | Default |
|----------|-----------|---------|
| `APP_PORT` | Porta do serviço | `8000` |
| `APP_ENV` | Ambiente | `production` |
| `APP_LOG_LEVEL` | Nível de log | `INFO` |
| `APP_DB_URL` | URL do banco de dados | — |

## Development

```bash
# instalar dependências
pip install -e ".[dev]"

# rodar testes
pytest

# rodar localmente
uvicorn src.main:app --reload

# lint
ruff check .

# type check
mypy src/
```

## Contributing

1. Fork o repositório
2. Crie sua branch: `git checkout -b feat/minha-feature`
3. Commit: `git commit -m 'feat: minha feature'`
4. Push: `git push origin feat/minha-feature`
5. Abra um Pull Request

Consulte [AGENTS.md](AGENTS.md) para diretrizes de desenvolvimento e convenções do projeto.

## License

Proprietary — dataforalltech © {{year}}
