# Terraform — Ambiente ENXUTO (HML / prod inicial)

Topologia mínima para **quase sem uso**: **1 EC2 rodando tudo** (app + data +
Vault via `../deploy/`) exposto por **Cloudflare Tunnel** — **sem ALB, sem NAT,
sem entrada pública** (o `cloudflared` conecta de dentro para fora). Serve tanto
**HML** quanto a **prod inicial**; escala-se depois com o Terraform completo
(`../terraform/`) quando o uso crescer.

## O que provisiona

| Recurso | Observação |
|---|---|
| VPC + 1 subnet pública + IGW | egress via IGW (sem NAT — economia) |
| 1 EC2 (`t3.xlarge`) + EBS gp3 de dados + DLM | roda todos os containers; SG **sem ingress** |
| Cloudflare Tunnel + DNS wildcard/ápice | origem sem entrada pública; TLS/WAF no edge (D6/D7) |
| SSM Parameter (token do tunnel) | o `cloudflared` lê no boot |
| IAM instance profile | ECR pull + S3 backups + SSM |
| S3 backups (KMS, versionado, privado) | dumps/snapshots lógicos |
| KMS | cifra EBS/S3 |

## Custo aproximado
~US$30–45/mês: 1 EC2 t3.xlarge (on-demand; use Savings Plan p/ ~40% off), ~100GB
EBS, S3 mínimo. **Sem** os custos de ALB (~US$18) e NAT (~US$32+) do desenho completo.

## Uso

```bash
export CLOUDFLARE_API_TOKEN=...            # token com Tunnel:Edit + DNS:Edit + Zone
cp terraform.tfvars.example terraform.tfvars   # zone_id, account_id, domain
terraform init && terraform plan && terraform apply
```

## Bootstrap pós-apply

1. **Acesse o host** (sem SSH): `aws ssm start-session --target <instance_id>`.
   O `user_data` já instalou Docker e conectou o `cloudflared` ao tunnel.
2. **Suba a stack** com os composes deste repo (`../deploy/`):
   ```bash
   export GITHUB_TOKEN=...            # build das libs privadas
   docker network create platform-local
   docker compose -f docker-compose.infra.yml    --env-file .env up -d
   docker compose -f docker-compose.services.yml --env-file .env up -d
   ```
   O gateway publica a porta `edge_port` (8080), para onde o tunnel roteia.
3. **Vault**: rode o container do Vault (dev/server) e carregue os segredos; em
   HML `VAULT_AUTH_METHOD=token` é suficiente.
4. **Dados em `/data`**: o volume EBS é montado em `/data` — aponte os volumes dos
   stores para lá e configure dump lógico para o bucket `s3_backups_bucket`.

## Escalar depois
Quando o uso crescer, migre para `../terraform/` (VPC multi-AZ, Swarm multi-nó,
data tier dedicado, ALB) — o mesmo `stack.yml` e composes servem os dois.
