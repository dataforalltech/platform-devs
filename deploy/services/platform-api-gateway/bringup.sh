#!/usr/bin/env bash
# bringup.sh — platform-api-gateway (API + MCP) no ambiente enxuto.
# Executado via SSM RunShellScript (root). Idempotente.
LOG=/var/log/dataforall-gateway.log
exec > >(tee -a "$LOG") 2>&1
echo "=== gateway $(date -u) ==="

BUCKET=dataforall-hml-backups-011756140303
REGION=us-east-1
NAME=dataforall-hml
ACR=d4all.azurecr.io
ENVF=/opt/dataforall/deploy/.env

# 1) tokens de servico no .env (gerados on-box se ausentes)
add_secret() { k="$1"; if ! grep -q "^${k}=" "$ENVF" 2>/dev/null; then printf '%s=%s\n' "$k" "$(openssl rand -hex 32)" >> "$ENVF"; echo "  + $k"; fi; }
add_secret INTERNAL_API_TOKEN
add_secret HEALTH_MONITORING_TOKEN
chmod 600 "$ENVF"

# 2) seed do admin DB (ADMIN_DATAFORALL + PLATFORMS + tenant app.dataforall.tech)
#    PLATFORMS inclui db_user/db_password (o auth le essas colunas p/ conectar no
#    DB do tenant — ver bring-up-errors-and-fixes.md F4). O DB do tenant e nomeado
#    pelo tenant_id (F5).
PW=$(grep '^MYSQL_ROOT_PASSWORD=' "$ENVF" | cut -d= -f2-)
TENANT_TOKEN=$(openssl rand -hex 32)
docker exec -i dataforall-admin-mysql mysql -uroot -p"$PW" <<SQL
CREATE DATABASE IF NOT EXISTS ADMIN_DATAFORALL CHARACTER SET utf8mb4;
USE ADMIN_DATAFORALL;
CREATE TABLE IF NOT EXISTS PLATFORMS (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  url VARCHAR(500) NOT NULL,
  internal_port INT NOT NULL,
  tenant_id VARCHAR(255) NOT NULL UNIQUE,
  internal_token VARCHAR(500) NOT NULL,
  domain VARCHAR(255) NULL UNIQUE,
  db_engine VARCHAR(50) NOT NULL DEFAULT 'mysql',
  db_host VARCHAR(255) NOT NULL,
  db_port INT NOT NULL,
  db_user VARCHAR(255) NULL,
  db_password VARCHAR(500) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  excluded TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO PLATFORMS (name,url,internal_port,tenant_id,internal_token,domain,db_engine,db_host,db_port,db_user,db_password,active,excluded)
VALUES ('HML app','https://app.dataforall.tech',8000,'dataforall','${TENANT_TOKEN}','app.dataforall.tech','mysql','tenant-mysql',3306,'root','${PW}',1,0)
ON DUPLICATE KEY UPDATE domain=VALUES(domain), db_host=VALUES(db_host), db_user=VALUES(db_user), db_password=VALUES(db_password), active=1, excluded=0;
SQL
# DB do tenant (nomeado pelo tenant_id) — o auth e demais servicos conectam aqui
docker exec dataforall-tenant-mysql mysql -uroot -p"$PW" -e "CREATE DATABASE IF NOT EXISTS dataforall CHARACTER SET utf8mb4;" 2>/dev/null && echo "DB tenant 'dataforall' ok"
echo "seed PLATFORMS:"; docker exec dataforall-admin-mysql mysql -uroot -p"$PW" -N -e "SELECT id,tenant_id,domain,db_user FROM ADMIN_DATAFORALL.PLATFORMS;" 2>/dev/null

# 3) login ACR (senha via SSM stdin)
ACR_USER=$(aws ssm get-parameter --region "$REGION" --name "/${NAME}/acr/username" --query Parameter.Value --output text)
aws ssm get-parameter --region "$REGION" --name "/${NAME}/acr/password" --with-decryption --query Parameter.Value --output text | docker login "$ACR" -u "$ACR_USER" --password-stdin >/dev/null && echo "login ACR ok"

# 4) sync manifests (NUNCA apagar .env) + pull + up API e MCP
aws s3 sync "s3://${BUCKET}/deploy" /opt/dataforall/deploy --region "$REGION" --exclude ".env" >/dev/null
cd /opt/dataforall/deploy/services/platform-api-gateway
docker compose --env-file "$ENVF" pull
docker compose --env-file "$ENVF" up -d --no-build

sleep 30
echo "=== status ==="; docker ps --filter name=platform-api-gateway --format 'table {{.Names}}\t{{.Status}}'
echo "=== FIM gateway ==="
