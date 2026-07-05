#!/usr/bin/env bash
# bringup-infra.sh — sobe a infra (data tier + Vault + observabilidade) na EC2 enxuta.
# Executado via SSM RunShellScript (roda como root). Idempotente.
#
#   aws ssm send-command --instance-ids <id> --document-name AWS-RunShellScript \
#     --parameters commands="$(cat bringup-infra.sh)"
#
# Pre-condicoes (feitas pelo user_data do Terraform): Docker, cloudflared, /data montado.
set -euo pipefail
LOG=/var/log/dataforall-bringup.log
exec > >(tee -a "$LOG") 2>&1
echo "=== bringup infra $(date -u) ==="

BUCKET="${BUCKET:-dataforall-hml-backups-011756140303}"
REGION="${REGION:-us-east-1}"

# 1) Docker data-root -> /data/docker (disco de 100G, nao o root de 40G)
mkdir -p /data/docker
if ! docker info 2>/dev/null | grep -q "Docker Root Dir: /data/docker"; then
  mkdir -p /etc/docker
  cat > /etc/docker/daemon.json <<'JSON'
{
  "data-root": "/data/docker",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
  systemctl restart docker
  sleep 6
fi
echo "Docker Root Dir: $(docker info 2>/dev/null | awk -F': ' '/Docker Root Dir/{print $2}')"

# 2) aws cli (para sync do S3)
if ! command -v aws >/dev/null 2>&1; then
  snap install aws-cli --classic || { apt-get update -y && apt-get install -y awscli; }
fi

# 3) sync deploy/ do S3
mkdir -p /opt/dataforall
# --exclude ".env": NUNCA remover o .env local (senhas geradas on-box, nao vao pro S3).
# Sem isso, --delete apaga o .env porque ele nao existe no bucket.
aws s3 sync "s3://${BUCKET}/deploy" /opt/dataforall/deploy --region "$REGION" --delete --exclude ".env"
cd /opt/dataforall/deploy

# 4) .env com senhas fortes geradas ON-BOX (nunca transitam pela rede/logs)
if [ ! -f .env ]; then
  umask 077
  {
    echo "MYSQL_ROOT_PASSWORD=$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-32)"
    echo "POSTGRES_PASSWORD=$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-32)"
    echo "REDIS_PASSWORD=$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-32)"
    echo "VAULT_ROOT_TOKEN=$(openssl rand -hex 24)"
    echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  } > .env
  chmod 600 .env
  echo ".env gerado (chmod 600)."
else
  echo ".env ja existe, mantido."
fi

# 5) rede externa compartilhada (services compose tambem a usa)
docker network create platform-local 2>/dev/null && echo "rede platform-local criada" || echo "rede platform-local ja existe"

# 6) subir a infra
docker compose -f docker-compose.infra.yml --env-file .env pull
docker compose -f docker-compose.infra.yml --env-file .env up -d

sleep 10
echo "=== docker ps ==="
docker ps --format 'table {{.Names}}\t{{.Status}}'
df -h / /data | tail -2
echo "=== FIM bringup ==="
