# Plataforma DataForAll — Visão Geral da Arquitetura e Operação

Documento-índice de tudo que foi definido e construído: arquitetura definitiva,
entrega de segredos, composes, stack de deploy, Terraform (completo e enxuto) e os
ambientes. Cada item aponta para o artefato canônico.

---

## 1. Arquitetura definitiva — as 7 decisões

Fonte de verdade: [official-stack-and-architecture.md](architecture/official-stack-and-architecture.md).

| # | Decisão | Escolha |
|---|---|---|
| **D1** | Camada stateful | MySQL, Postgres, Redis, Kafka **em container na EC2** (não RDS/ElastiCache/MSK) + hardening (EBS, snapshots, réplica, TLS) |
| **D2** | Persistência | **3 instâncias**: `admin-mysql` (registry, compartilhado) + `tenant-mysql` + `tenant-postgres` (dados por tenant, em runtime). Não é um banco por serviço |
| **D3** | Registry | **ACR** hoje → **ECR** como alvo |
| **D4** | Compute / HA | **Docker Swarm** (sem Portainer), múltiplas EC2, **escala estática** |
| **D5** | Segredos | **HashiCorp Vault KV + AWS IAM auth** (ADR-0006) |
| **D6** | DNS / borda | **Cloudflare** (DNS/WAF/edge) → ALB (ou Tunnel no enxuto) |
| **D7** | Multi-tenancy | **Por domínio**: o `Host` é a identidade do tenant; o gateway resolve `Host → PLATFORMS.domain → tenant_id` |

Detalhe visual: Artifact publicado (arquitetura + topologia + fluxo de tenancy).

---

## 2. Entrega de segredos (D5) — Vault KV

- `platform-crypto-lib` **v0.2.0**: `VaultSecretsClient` + auth **AWS** (EC2 instance
  profile via STS), Kubernetes e AppRole. Fetch no boot, cache em memória, fail-closed.
- `platform-auth`: `app/core/vault_loader.py` + validador `_load_from_vault`; chave RSA
  do JWT entregue pelo Vault. Azure Key Vault **aposentado** (ADR-0006 substitui ADR-0005).
- Runbook: [vault-kv-setup](https://github.com/dataforalltech/platform-auth/blob/develop/docs/runbooks/vault-kv-setup.md).
- **Status:** mergeado em `develop` (crypto-lib PR #1 + tag v0.2.0; auth já em develop).

---

## 3. Deploy — composes e stack Swarm

Em [`../deploy/`](../deploy/) e no `platform-service-template`:

| Artefato | O quê |
|---|---|
| `platform-service-template/deploy/stack.yml` | **Stack Swarm de produção** parametrizado que TODOS os serviços herdam (replicas/placement-AZ/update_config/healthcheck/resources) |
| `deploy/docker-compose.infra.yml` | Infra local: MySQL admin+tenant, Postgres, Redis, Kafka, Vault, Prometheus/Grafana/OTel/Tempo |
| `deploy/docker-compose.services.yml` | 29 serviços (anchors YAML, DB por engine, build local ou imagem ACR) |
| `deploy/docker-compose.data.yml` / `.observability.yml` | Data tier (per-host) e observabilidade (Swarm) para produção |

Multi-tenancy por domínio (D7): autoritativo em
[ADR-001 do gateway](https://github.com/dataforalltech/platform-api-gateway/blob/develop/docs/ADR-001-domain-tenancy-jwt-flow.md).

---

## 4. Infraestrutura AWS — dois ambientes

### 4a. Enxuto — HML / prod inicial (uso quase zero)
[`../terraform-lean/`](../terraform-lean/) — **1 EC2 rodando tudo + Cloudflare Tunnel**
(sem ALB, sem NAT, origem sem entrada pública). **~29 recursos**. Custo mensal
sa-east-1: **~US$90 (t3.large 8GB + Savings Plan)** a **~US$227 (t3.xlarge on-demand)**;
**~US$72** parando fora do horário (HML). Serve HML **e** a prod que está começando;
escala-se depois. `terraform plan` = **29 to add, 0 erros**.

### 4b. Completo — produção com carga (alvo de escala)
[`../terraform/`](../terraform/) — VPC multi-AZ, EC2 do Swarm (managers+workers) +
data tier dedicado (EC2+EBS gp3+DLM), Vault (AWS auth+KMS), ALB+ACM wildcard com
bloqueio de rotas internas, ECR (29 repos), S3. **152 recursos**. `terraform plan` = **152 to add, 0 erros**.

> Os dois usam o **mesmo `stack.yml` e composes**. Migração enxuto→completo é trocar
> de diretório Terraform quando o uso crescer.

**Playbook operacional de deploy em produção:**
[aws-production-deployment-playbook.md](runbooks/aws-production-deployment-playbook.md).

---

## 5. Segurança — pontos verificados / abertos

- **Borda (D7):** o `Host` decide o tenant → a origem não pode ser acessível fora da
  Cloudflare. No completo: SG do ALB só IPs Cloudflare + WAF. No enxuto: **Tunnel**
  (origem sem entrada pública) já garante isso.
- **Achado (gateway):** a porta do gateway estava publicada em `0.0.0.0` — fechar ao
  loopback + SG (tarefa aberta).
- **Achado (build):** vários repos falham o build por declararem `platform-database-lib`
  como dep de versão (privada, não está no PyPI) — corrigir para git dep (tarefa em
  andamento). Padrão em [private-lib-packaging](../..).

---

## 6. Como subir (resumo)

**Enxuto (HML):**
```bash
cd terraform-lean && terraform apply         # 1 EC2 + Tunnel
# no host (via SSM): docker compose -f deploy/docker-compose.infra.yml up -d
#                     docker compose -f deploy/docker-compose.services.yml up -d
```

**Completo (escala):**
```bash
cd terraform && terraform apply              # VPC/Swarm/data/ALB/ECR
# bootstrap Swarm + stack deploy dos serviços (ver terraform/README.md)
```

---

## 7. Estado (2026-07-05)

- Arquitetura definitiva, composes, stack, Terraform completo e enxuto: **em `develop`**
  (PRs #1, #15, #16, #17 mergeados; enxuto + esta doc no PR corrente).
- Terraform validado por `plan` real (conta AWS `011756140303`, zona `dataforall.tech`).
- Pendentes: correção de empacotamento das libs (tarefa), `terraform apply` (decisão
  com custo), rebuild completo dos serviços após o fix de empacotamento.
