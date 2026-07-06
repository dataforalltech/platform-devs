# Testar os DevTeam localmente (em outra sessão do Claude Code)

Caminho turnkey para subir os 8 DevTeam + o Authorization Server em `localhost` e
conectá-los ao Claude Code — sem TLS, sem Caddy, sem Postgres (tudo in-memory).

## 1. Suba o stack de dev

```bash
docker compose -f deploy/dev/docker-compose.dev.yml up -d --build
```

Isso publica em localhost:

| Serviço | URL |
|---|---|
| auth-mcp (Authorization Server) | http://localhost:7103 |
| architecture | http://localhost:7118/mcp |
| backend | http://localhost:7119/mcp |
| frontend | http://localhost:7120/mcp |
| devops | http://localhost:7121/mcp |
| product-owner | http://localhost:7122/mcp |
| product-manager | http://localhost:7123/mcp |
| qa-engineer | http://localhost:7124/mcp |
| security | http://localhost:7125/mcp |

Confira a saúde: `curl http://localhost:7103/v1/health` e `curl http://localhost:7125/v1/health`.

## 2. Registre os DevTeam no Claude Code

O script emite um token de teste por DevTeam (via `client_credentials`, TTL de ~1 dia) e
imprime/roda os comandos `claude mcp add`:

```bash
# só imprime os comandos (cole onde quiser):
python scripts/dev_connect.py

# ou registra automaticamente (escopo user = vale em todas as suas sessões):
python scripts/dev_connect.py --run --scope user
```

Cada comando fica assim:
```
claude mcp add --transport http --scope user security http://localhost:7125/mcp \
  --header "Authorization: Bearer <token-de-1-dia>"
```

## 3. Use em outra sessão

Abra uma **nova sessão** do Claude Code (as configs com `--scope user` valem globalmente):

```bash
claude mcp list          # os 8 devteam devem aparecer como "connected"
```

Peça, por exemplo: *"use o security para calcular o CVSS do vetor
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"* ou *"use o backend para gerar um
router FastAPI de usuários"*.

## 4. Derrubar

```bash
docker compose -f deploy/dev/docker-compose.dev.yml down
# remover os MCPs do Claude Code (se usou --run):
for z in security qa-engineer architecture backend frontend devops product-owner product-manager; do claude mcp remove $z; done
```

## Notas

- **Auth continua ativa** — os DevTeam exigem o Bearer; o token carrega `aud` = a URL do
  próprio DevTeam e o escopo por ferramenta. É o mesmo modelo de produção, só sem TLS/borda.
- O token expira (~1 dia). Para renovar: re-rode `python scripts/dev_connect.py --run`.
- Este modo usa o client de DEMO `security-dev` (secret `dev-secret-change-me`) com escopo de
  todos os DevTeam. **Só para dev.** Produção usa `docker-compose.pilot.yml` (Caddy+TLS+OAuth/Keycloak).
- Se preferir o fluxo OAuth de browser (login real) em vez do Bearer estático, use o stack de
  produção + Keycloak (ver `deploy/keycloak/README.md`).
```
