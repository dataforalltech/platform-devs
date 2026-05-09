# Camada Infrastructure

Infra define onde e como o serviço roda. Mudanças aqui afetam todos os ambientes.

## Pode

- Atualizar versão de imagem base com justificativa.
- Adicionar variável de ambiente em `.env.example` documentada.
- Ajustar healthcheck/probes conforme contrato.
- Adicionar novo serviço ao docker-compose seguindo padrão do template.

## Não pode

- Commitar `.env` real, secrets, certificados, tokens.
- Pular hooks/CI com `--no-verify` ou flags equivalentes.
- Mudar `.gitignore`/`pyproject.toml`/`package.json` sem necessidade da tarefa.
- Alterar pipeline de CI/CD sem aprovação humana.
- Subir imagem sem tag versionada.

## Errado

```dockerfile
# Secret no Dockerfile
ENV API_TOKEN=sk-real-token-abcdefghij
```

```yaml
# docker-compose com porta hardcoded sem env
services:
  app:
    ports:
      - "8000:8000"  # se for fixo, está OK; se varia por ambiente, parametrize
    environment:
      DATABASE_URL: postgresql://user:pass@db/app  # senha em compose
```

```bash
# Pulando hooks
git commit --no-verify -m "fix"
```

## Correto

```dockerfile
# Secret injetado em runtime
ENV API_TOKEN
# valor virá do orquestrador (k8s secret, ECS task def, etc.)
```

```yaml
services:
  app:
    image: registry.example.com/app:1.4.2  # tag versionada
    environment:
      DATABASE_URL: ${DATABASE_URL}  # vem do .env (que está no .gitignore)
```

## Convenções

- Imagens com tag semver explícita (`:1.4.2`), nunca `:latest` em produção.
- Variável de ambiente nova → documentar em `.env.example` + README.
- Healthcheck obrigatório em todo serviço HTTP (`/health/live`, `/health/ready`).
- Secrets via cofre / k8s secret / SOPS / sealed-secrets — nunca em commit.

## Hard stops

- Você encontrou secret no histórico do git → escale, rotacione, limpe histórico.
- Build vai pular hook/test → não. Corrija a causa.
- Imagem `:latest` em produção → corrigir antes do deploy.

---

## Ambientes e NETWORK_TOPOLOGY

Cada `.env.*` declara `NETWORK_TOPOLOGY` que define como URLs inter-serviço são resolvidas:

| Valor | Quando | Formato de URL interna |
|---|---|---|
| `host` | Dev local fora do Docker | `http://localhost:{porta-reservada}` |
| `docker` | Cloud / Docker Compose completo | `http://{container-name}:{porta-interna}` |
| `cross-network` | Híbrido local + cloud | `https://{stage}.api.dataforall.com/{svc}` |

**Serviço dentro do Docker que precisa chamar serviço no host:**
```
URL = http://host.docker.internal:{porta-reservada}
```

**Seleção do arquivo `.env.*`:**
```bash
# Shell / Makefile — controla qual env carregar
APP_ENV_FILE=.env.dev.local uvicorn app.main:app --reload
```

Convenção de arquivos: `.env.dev.local` | `.env.dev.cloud` | `.env.hml.cloud` | `.env.prod.cloud`.

## GATEWAY_MAPPING (tabela ADMIN_DATAFORALL)

Controla roteamento HTTP e WebSocket no `platform-api-gateway`:

| Campo | Função |
|---|---|
| `internal_url` | URL de destino (ex: `http://host.docker.internal:8004`) |
| `path_prefix` | Prefixo de rota HTTP que o gateway reconhece |
| `strip_prefix` | `1` = remove o prefixo antes de encaminhar; `0` = mantém |
| `additional_info.ws_prefix` | Prefixo de rota WebSocket (ex: `"/bi"`) |

**Atenção:** `path_prefix` deve bater com as rotas internas do serviço.  
Exemplo: analytics expõe `/api/v1/bi/...` → `path_prefix = /bi`, `strip_prefix = 0`.  
Se `path_prefix = /analytics` mas serviço responde em `/bi`, o gateway aceita mas o serviço retorna 404.
