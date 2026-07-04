# Deploy de produção — Docker Swarm (DataForAll)

Arquivos para subir a plataforma em produção, alinhados à
[arquitetura definitiva](../docs/architecture/official-stack-and-architecture.md)
e ao [playbook](../docs/runbooks/aws-production-deployment-playbook.md).

| Arquivo | O quê | Onde roda |
|---|---|---|
| `platform-service-template/deploy/stack.yml` | Stack Swarm de **um serviço** (parametrizado) | app tier (cluster Swarm) |
| `platform-service-template/deploy/stack.env.example` | Variáveis por serviço (sem segredos) | — |
| `deploy/docker-compose.data.yml` | **Data tier**: MySQL, Postgres, Redis, Kafka + exporters | EC2 de dados dedicada (fora do Swarm) |
| `deploy/docker-compose.observability.yml` | Prometheus, Grafana, OTel, Tempo | stack Swarm (nó `obs`) |
| `deploy/config/*` | Configs de Prometheus/Tempo/OTel | — |

> **Um stack para todos os serviços.** Os ~62 serviços diferem só por nome, porta,
> DB e réplicas — tudo via `stack.env`. Não há um compose por serviço; usa-se o
> mesmo `stack.yml` com variáveis diferentes.

---

## 0. Pré-requisitos do cluster (uma vez)

```bash
# Inicializar o Swarm (no primeiro manager) e juntar os demais nós
docker swarm init --advertise-addr <ip-privado-manager>
# (nos outros nós) docker swarm join --token <token> <manager>:2377

# Rede overlay compartilhada por todos os serviços
docker network create -d overlay --attachable platform

# Rotular nós por AZ (para o spread do placement) e o nó de observabilidade
docker node update --label-add az=a  <no-az-a>
docker node update --label-add az=b  <no-az-b>
docker node update --label-add obs=true <no-observabilidade>   # de preferência um manager

# Login no registry (ACR hoje) — para os nós puxarem as imagens
docker login d4all.azurecr.io
```

---

## 1. Onda 0 — Data tier + Observabilidade

**Data tier** (em cada EC2 de dados, só o profile daquele host). Senhas do Vault:

```bash
export DATA_BIND_IP=<ip-privado-da-ec2>
export MYSQL_ROOT_PASSWORD=$(vault kv get -field=value kv/dataforall/data/mysql_root)
docker compose -f deploy/docker-compose.data.yml --profile mysql up -d
# idem para --profile postgres | redis | kafka nos respectivos hosts
```

**Observabilidade** (stack Swarm):

```bash
export GRAFANA_ADMIN_PASSWORD=$(vault kv get -field=value kv/dataforall/obs/grafana_admin)
docker stack deploy -c deploy/docker-compose.observability.yml observability
```

*Gate:* exporters e serviços aparecendo em `Status → Targets` no Prometheus.

---

## 2. Ondas 1–3 — Serviços (o mesmo procedimento para todos)

Para **cada** serviço, na ordem das ondas (auth/admin → gateway → domínio):

```bash
cp platform-service-template/deploy/stack.env.example stack.env
# edite stack.env: SERVICE_NAME, IMAGE_TAG, DB_ENGINE/DB_HOST/DB_NAME, REPLICAS, VAULT_ADDR...

export $(grep -v '^#' stack.env | xargs)
docker stack deploy -c platform-service-template/deploy/stack.yml "$SERVICE_NAME" --with-registry-auth

# acompanhar a convergência (rolling update start-first)
docker service ps "${SERVICE_NAME}_app"
```

Só os serviços de **borda** (`platform-api-gateway`, frontend) publicam porta para a
ALB — descomente o bloco `ports:` no `stack.yml` e defina `PUBLISHED_PORT`. Os
demais são alcançados **internamente** pela overlay (`http://platform-auth:8000`).

---

## 3. Operação

```bash
# Escala ESTÁTICA (D4) — ajuste manual de réplicas
docker service scale platform-auth_app=3

# Rollback (imagem anterior ainda no registry)
docker service rollback platform-auth_app

# Logs / estado
docker service logs -f platform-auth_app
docker stack services platform-auth
```

---

## Notas de segurança (obrigatórias)

- **Segredos:** nenhum neste diretório. App tier busca do **Vault via AWS IAM auth**
  (D5); data tier recebe senhas do Vault via env exportado no host.
- **Rede:** as EC2 de dados só aceitam as portas de dados a partir do **SG do app
  tier**; a única entrada pública é a **ALB:443** (atrás da Cloudflare).
- **TLS:** obrigatório no data tier — monte os certs em `deploy/certs/<store>/`.
- **Backup:** snapshots EBS (DLM) + dump lógico para S3, com restore testado (§5 da stack).
