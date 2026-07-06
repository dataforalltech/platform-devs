#!/usr/bin/env bash
# onboard-tenant.sh <tenant_id> [admin_email] [admin_password]
# Provisiona um tenant no ambiente enxuto (idempotente o suficiente p/ reexecutar):
#   1. cria o database do tenant (nomeado pelo tenant_id) no tenant-mysql
#   2. roda as migrations Alembic do platform-admin (tabelas IAM adm_*)
#   3. roda as migrations Alembic do platform-auth (auth_refresh_tokens, etc.)
#   4. semeia um superadmin (adm_users_profile + adm_users + adm_users_login_config)
#
# Pre-req: platform-admin e platform-auth no ar (as migrations rodam DENTRO deles).
# Ver bring-up-errors-and-fixes.md secao F (F5/F8/F9).
#
#   ./onboard-tenant.sh dataforall admin@dataforall.tech 'Dataforall@2026'
set -uo pipefail
TENANT="${1:?uso: onboard-tenant.sh <tenant_id> [email] [senha]}"
EMAIL="${2:-admin@${TENANT}.tech}"
UPASS="${3:-Dataforall@2026}"
ENVF=/opt/dataforall/deploy/.env
PW=$(grep '^MYSQL_ROOT_PASSWORD=' "$ENVF" | cut -d= -f2-)

echo "== 1. cria DB do tenant '$TENANT' =="
docker exec dataforall-tenant-mysql mysql -uroot -p"$PW" -e "CREATE DATABASE IF NOT EXISTS \`$TENANT\` CHARACTER SET utf8mb4;" 2>/dev/null

# alembic: passar -x db_host EXPLICITO (o env.py cai no ADMIN_DB por padrao -> 'Unknown database')
XARGS="-x tenant_id=$TENANT -x db_engine=mysql -x db_host=tenant-mysql -x db_port=3306 -x db_user=root -x db_password=$PW -x db_name=$TENANT"
echo "== 2. migrations do platform-admin =="
docker exec -w /app platform-admin sh -c "alembic $XARGS upgrade head" 2>&1 | grep -iE 'running upgrade|error|already' | tail -6
echo "== 3. migrations do platform-auth =="
docker exec -w /app platform-auth sh -c "alembic $XARGS upgrade head" 2>&1 | grep -iE 'running upgrade|error|already' | tail -6
# demais servicos com estado (best-effort: so se o container existir)
for svc in platform-governance platform-notification platform-connectors; do
  if docker ps --format '{{.Names}}' | grep -q "^${svc}$"; then
    echo "== 3b. migrations do ${svc} =="
    docker exec -w /app "$svc" sh -c "alembic $XARGS upgrade head" 2>&1 | grep -iE 'running upgrade|error|already' | tail -6
  fi
done

echo "== 4. seed superadmin ($EMAIL) =="
EXISTS=$(docker exec dataforall-tenant-mysql mysql -uroot -p"$PW" -N -e "SELECT COUNT(*) FROM \`$TENANT\`.adm_users WHERE email='$EMAIL';" 2>/dev/null)
if [ "${EXISTS:-0}" -gt 0 ]; then
  echo "  usuario ja existe, pulando"
else
  HASH=$(docker exec platform-admin python -c "from app.core.password import hash_password; print(hash_password('$UPASS'))" 2>/dev/null | tr -d '\r')
  docker exec -i dataforall-tenant-mysql mysql -uroot -p"$PW" "$TENANT" 2>&1 <<SQL | grep -iv insecure
INSERT INTO adm_users_profile (id_user_created,active,excluded,name,role,is_deleted,is_active) VALUES (1,1,0,'Superadmin','superadmin',0,1);
SET @pid=LAST_INSERT_ID();
INSERT INTO adm_users (id_user_created,active,excluded,username,password,name,email,idf_access_profile,status,is_deleted,is_active)
 VALUES (1,1,0,'admin','${HASH}','Administrator','${EMAIL}',@pid,'active',0,1);
SET @uid=LAST_INSERT_ID();
INSERT INTO adm_users_login_config (id_user_created,active,excluded,idf_user,login_type,is_deleted,is_active) VALUES (1,1,0,@uid,'basic_login',0,1);
SQL
  echo "  superadmin criado ($EMAIL / senha fornecida)"
fi
echo "== tenant '$TENANT' pronto =="
