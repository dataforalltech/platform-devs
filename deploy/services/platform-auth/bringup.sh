#!/usr/bin/env bash
# bringup.sh — platform-auth (API + MCP) no ambiente enxuto.
# Chave RSA: fonte durável no S3 (s3://<bucket>/secrets/platform-auth-jwt.pem) e
# tambem seedada no Vault (kv/dataforall/platform-auth/jwt_private_key). O auth le
# via arquivo montado + JWT_PRIVATE_KEY_PATH (env vence Vault neste build — F1).
# Ver bring-up-errors-and-fixes.md secao F.
LOG=/var/log/dataforall-auth.log
exec > >(tee -a "$LOG") 2>&1
echo "=== auth $(date -u) ==="
BUCKET=dataforall-hml-backups-011756140303
REGION=us-east-1
NAME=dataforall-hml
ACR=d4all.azurecr.io
ENVF=/opt/dataforall/deploy/.env
VT=$(grep '^VAULT_ROOT_TOKEN=' "$ENVF" | cut -d= -f2-)
KEYFILE=/opt/dataforall/deploy/secrets/jwt-auth.pem
S3KEY="s3://${BUCKET}/secrets/platform-auth-jwt.pem"

# 1) chave RSA: restaura do S3 se existir; senao gera, sobe pro S3 e seedа no Vault
mkdir -p /opt/dataforall/deploy/secrets
if aws s3 cp "$S3KEY" "$KEYFILE" --region "$REGION" --only-show-errors 2>/dev/null && grep -q "PRIVATE KEY" "$KEYFILE"; then
  echo "chave RSA restaurada do S3"
else
  echo "gerando RSA 2048..."
  openssl genrsa -out "$KEYFILE" 2048 2>/dev/null
  aws s3 cp "$KEYFILE" "$S3KEY" --region "$REGION" --only-show-errors && echo "chave salva no S3"
fi
chmod 644 "$KEYFILE" # F2: processo do auth (nao-root) precisa ler o arquivo montado
# seed no Vault (kv v2) — best effort (dev mode; env vence de qualquer forma)
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VT" dataforall-vault vault secrets enable -path=kv -version=2 kv 2>/dev/null || true
cat "$KEYFILE" | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VT" dataforall-vault vault kv put -mount=kv dataforall/platform-auth/jwt_private_key pem=- >/dev/null 2>&1 && echo "chave seedada no Vault"

# 2) login ACR + sync + up API e MCP
ACR_USER=$(aws ssm get-parameter --region "$REGION" --name "/${NAME}/acr/username" --query Parameter.Value --output text)
aws ssm get-parameter --region "$REGION" --name "/${NAME}/acr/password" --with-decryption --query Parameter.Value --output text | docker login "$ACR" -u "$ACR_USER" --password-stdin >/dev/null && echo "login ACR ok"
aws s3 sync "s3://${BUCKET}/deploy" /opt/dataforall/deploy --region "$REGION" --exclude ".env" --exclude "secrets/*" >/dev/null
cd /opt/dataforall/deploy/services/platform-auth
docker compose --env-file "$ENVF" pull
docker compose --env-file "$ENVF" up -d --no-build

# 3) aponta a rota do gateway p/ o container (E4)
sleep 30
bash /opt/dataforall/deploy/seed/fix-gateway-route.sh platform-auth 8000 || true

echo "=== status ==="; docker ps --filter name=platform-auth --format 'table {{.Names}}\t{{.Status}}'
echo "=== FIM auth ==="
