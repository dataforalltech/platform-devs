# Terraform — Landing Zone AWS (Plataforma DataForAll)

Provisiona a infra da AWS alinhada às decisões definitivas (ver
[official-stack-and-architecture.md](../docs/architecture/official-stack-and-architecture.md)):

| Recurso | Arquivo | Decisão |
|---|---|---|
| VPC, subnets públicas/privadas (≥2 AZs), NAT, rotas | `network.tf` | HA (D4) |
| Security Groups (ALB só Cloudflare, app←ALB, data←app, vault←app) | `security.tf` | D6/D7 |
| IAM instance profiles (app/data/vault) | `iam.tf` | D5 |
| App tier — EC2 do Swarm (managers + workers, escala estática) | `compute.tf` | D4 |
| Data tier — EC2 dedicada por store + EBS gp3 + snapshots DLM | `compute.tf` | D1 (§5) |
| Vault — EC2 + role p/ AWS auth + KMS unseal | `compute.tf`, `iam.tf` | D5 |
| ALB + ACM wildcard + bloqueio de `/internal`,`/platform-admin`,`/lab` | `alb.tf` | D6/D7 |
| ECR (repo por serviço, immutable, scan on push) | `storage.tf` | D3 |
| S3 (logs + backups, cifrados, versionados) | `storage.tf` | §5 |
| DNS Cloudflare (wildcard + ápice → ALB, proxied) | `dns.tf` | D6/D7 |

> Data stores **como container em EC2** (D1) — não RDS/ElastiCache/MSK. O
> Terraform provisiona as **instâncias + volumes**; os containers sobem pelos
> composes (`../deploy/`) no bootstrap.

## Pré-requisitos

```bash
export AWS_PROFILE=...                 # ou credenciais via SSO/role
export CLOUDFLARE_API_TOKEN=...        # token com Zone:DNS:Edit na zona
cp terraform.tfvars.example terraform.tfvars   # preencha zone_id, domain, key_name...
```

## Uso

```bash
terraform init
terraform plan
terraform apply
```

## Bootstrap pós-apply (passos operacionais)

Os `user_data` já instalam Docker. O restante é operacional:

1. **Swarm**: no 1º manager `docker swarm init --advertise-addr <ip-privado>`;
   nos demais nós `docker swarm join --token <...> <manager>:2377`
   (IPs nos outputs `app_manager_private_ips` / `app_worker_private_ips`).
2. **Data tier**: em cada EC2 de dados, formatar/montar o volume EBS
   (`/dev/sdf` → `/data`) e subir o store via `../deploy/docker-compose.infra.yml`
   (ou o compose por store). Configurar réplica na 2ª AZ + backup para o bucket
   `s3_backups_bucket`.
3. **Vault**: iniciar o Vault na instância, habilitar KV v2 + **aws auth**, e
   criar a role ligada ao `iam_app_role_arn` (output) — ver
   [runbook do Vault](https://github.com/dataforalltech/platform-auth/blob/develop/docs/runbooks/vault-kv-setup.md).
4. **Deploy**: `docker stack deploy` dos serviços (ver
   `platform-service-template/deploy/stack.yml`), com a porta de borda
   (`edge_published_port`) publicada no gateway para o target group da ALB.
5. **Cloudflare**: confirmar *Authenticated Origin Pulls* (mTLS) e regras de WAF
   na zona (o SG do ALB já restringe aos IPs da Cloudflare).

## Notas

- **IMDSv2 obrigatório**, EBS/S3 **cifrados por KMS**, buckets sem acesso público.
- **Registry**: ECR provisionado (alvo D3); enquanto o CD ainda usa ACR, os repos
  ficam prontos para a migração.
- Recomenda-se **backend remoto** do state (bloco comentado em `versions.tf`).
