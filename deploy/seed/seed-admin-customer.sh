#!/usr/bin/env bash
# seed-admin-customer.sh <email> [senha]
# Cria um customer (admin-plane) em ADMIN_DATAFORALL.CUSTOMERS com hash bcrypt do
# proprio backend (platform-dataforall-admin app.core.security.hash_password).
# Login: POST /api/v1/customers/login em admin.data4all.com.br.
# NAO e tenant-scoped (ADMIN_DATAFORALL, nao tenant-mysql). Idempotente por email.
# Roda NO BOX. A senha e sua (nao fica hardcoded).
#
#   ./seed-admin-customer.sh admin@data4all.com.br 'SenhaForte!'
set -uo pipefail
EMAIL="${1:?uso: seed-admin-customer.sh <email> [senha]}"
UPASS="${2:-}"
[ -z "$UPASS" ] && { read -rs -p "Senha p/ ${EMAIL}: " UPASS; echo; }
[ -z "$UPASS" ] && { echo "senha vazia — abortando"; exit 1; }
EMAIL=$(printf '%s' "$EMAIL" | tr 'A-Z' 'a-z')   # backend faz email.lower() no lookup
PW=$(grep '^MYSQL_ROOT_PASSWORD=' /opt/dataforall/deploy/.env | cut -d= -f2-)
HASH=$(docker exec platform-dataforall-admin python -c "from app.core.security import hash_password; print(hash_password('$UPASS'))" 2>/dev/null | tr -d '\r')
[ -z "$HASH" ] && { echo "FALHA ao gerar hash (platform-dataforall-admin no ar?)"; exit 1; }
docker exec -i dataforall-admin-mysql mysql -uroot -p"$PW" ADMIN_DATAFORALL 2>&1 <<SQL | grep -viE 'insecure'
INSERT INTO \`CUSTOMERS\` (email, name, password_hash, status)
VALUES ('$EMAIL', 'Super Admin', '$HASH', 'active')
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash), name=VALUES(name), status='active', is_deleted=0;
SQL
echo "OK: customer '$EMAIL' semeado em ADMIN_DATAFORALL.CUSTOMERS (login em /api/v1/customers/login)"
