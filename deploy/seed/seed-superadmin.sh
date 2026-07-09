#!/usr/bin/env bash
# seed-superadmin.sh <tenant_id> <email> [senha] [role]
# Semeia um usuário (default role=superadmin) no DB do tenant:
#   adm_users_profile (role) + adm_users (hash real via platform-admin) + adm_users_login_config
# Idempotente: pula se o email já existir. Parametrizável por role (superadmin|admin|user|viewer)
# — dá p/ semear também os usuários de teste de RBAC.
#
# Pré-req: DB do tenant + tabelas adm_* já existem (onboard-tenant.sh ou onboarding de infra).
# Roda NO BOX (usa docker exec). A senha é sua — não fica hardcoded aqui.
#
#   ./seed-superadmin.sh PLATFORM_DATAFORALL_ADMIN admin@data4all.com.br 'SenhaForte!'
#   ./seed-superadmin.sh PLATFORM_DATAFORALL_SALES viewer@data4all.com.br 'x' viewer
#   ./seed-superadmin.sh PLATFORM_DATAFORALL_ADMIN admin@data4all.com.br     # (pergunta a senha)
set -uo pipefail
T="${1:?uso: seed-superadmin.sh <tenant_id> <email> [senha] [role]}"
EMAIL="${2:?email}"
UPASS="${3:-}"
ROLE="${4:-superadmin}"

if [ -z "$UPASS" ]; then read -rs -p "Senha p/ ${EMAIL} (${ROLE} @ ${T}): " UPASS; echo; fi
[ -z "$UPASS" ] && { echo "senha vazia — abortando"; exit 1; }

PW=$(grep '^MYSQL_ROOT_PASSWORD=' /opt/dataforall/deploy/.env | cut -d= -f2-)

EXISTS=$(docker exec dataforall-tenant-mysql mysql -uroot -p"$PW" -N \
  -e "SELECT COUNT(*) FROM \`$T\`.adm_users WHERE email='$EMAIL';" 2>/dev/null)
if [ "${EXISTS:-0}" -gt 0 ]; then
  echo "'$EMAIL' já existe no tenant '$T' — nada a fazer (idempotente)"; exit 0
fi

# Senha via env (SEED_PW) lida por os.environ no container — NUNCA interpolar a
# senha inline no `python -c`: chars como $, `, \ seriam expandidos pelo shell
# antes do Python e o hash sairia de uma string diferente da senha real.
HASH=$(docker exec -e SEED_PW="$UPASS" platform-admin \
  python -c "import os; from app.core.password import hash_password; print(hash_password(os.environ['SEED_PW']))" 2>/dev/null | tr -d '\r')
[ -z "$HASH" ] && { echo "FALHA ao gerar hash (platform-admin está no ar?)"; exit 1; }

docker exec -i dataforall-tenant-mysql mysql -uroot -p"$PW" "$T" 2>&1 <<SQL | grep -iv insecure
INSERT INTO adm_users_profile (id_user_created,active,excluded,name,role,is_deleted,is_active)
 VALUES (1,1,0,CONCAT(UPPER(SUBSTRING('${ROLE}',1,1)),SUBSTRING('${ROLE}',2)),'${ROLE}',0,1);
SET @pid=LAST_INSERT_ID();
INSERT INTO adm_users (id_user_created,active,excluded,username,password,name,email,idf_access_profile,status,is_deleted,is_active)
 VALUES (1,1,0,SUBSTRING_INDEX('${EMAIL}','@',1),'${HASH}','${ROLE}','${EMAIL}',@pid,'active',0,1);
SET @uid=LAST_INSERT_ID();
INSERT INTO adm_users_login_config (id_user_created,active,excluded,idf_user,login_type,is_deleted,is_active)
 VALUES (1,1,0,@uid,'basic_login',0,1);
SQL
echo "OK: usuário '$EMAIL' (role=$ROLE) semeado no tenant '$T'"
