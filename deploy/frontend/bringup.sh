#!/usr/bin/env bash
set -euo pipefail
LOG=/var/log/dataforall-frontend.log
exec > >(tee -a "$LOG") 2>&1
echo "=== frontend $(date -u) ==="

BUCKET=dataforall-hml-backups-011756140303
REGION=us-east-1
NAME=dataforall-hml
ACR=d4all.azurecr.io

# 1) sync dos manifests (deploy/ inteiro; inclui frontend/)
aws s3 sync "s3://${BUCKET}/deploy" /opt/dataforall/deploy --region "$REGION" --delete
cd /opt/dataforall/deploy/frontend

# 2) docker login no ACR (senha via SSM SecureString -> stdin; nunca em argv/log)
ACR_USER="$(aws ssm get-parameter --region "$REGION" --name "/${NAME}/acr/username" --query Parameter.Value --output text)"
aws ssm get-parameter --region "$REGION" --name "/${NAME}/acr/password" --with-decryption --query Parameter.Value --output text \
  | docker login "$ACR" -u "$ACR_USER" --password-stdin
echo "login ACR ok (user=$ACR_USER)"

# 3) pull + up (só a imagem do ACR; sem build)
docker compose -f docker-compose.frontend.yml pull
docker compose -f docker-compose.frontend.yml up -d --no-build

sleep 6
echo "=== docker ps (frontend) ==="
docker ps --filter name=dataforall-frontend --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo "=== healthz local ==="
curl -fsS -m 5 http://127.0.0.1:8080/healthz && echo "  <- 200 OK" || echo "  <- healthz falhou"
echo "=== index (primeiros bytes) ==="
curl -fsS -m 5 http://127.0.0.1:8080/ | head -c 200; echo
echo "=== FIM frontend ==="
