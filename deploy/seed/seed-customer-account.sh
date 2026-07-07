#!/usr/bin/env bash
# seed-customer-account.sh <email> [senha]
# Cria uma account self-service no customer-admin (tabela `accounts`, hash Argon2id
# do proprio backend) no tenant DB PLATFORM_DATAFORALL_CUSTOMER_ADMIN.
# Login: POST /api/v1/auth/login em platform.d4all.com.br.
# status='active_trial' (login rejeita 'pending_verification'). Idempotente por email.
# Roda NO BOX. Senha sua (nao hardcoded; evite aspas simples na senha).
#
#   ./seed-customer-account.sh admin@platform.d4all.com.br 'SenhaForte!'
set -uo pipefail
EMAIL="${1:?uso: seed-customer-account.sh <email> [senha]}"
UPASS="${2:-}"
[ -z "$UPASS" ] && { read -rs -p "Senha p/ ${EMAIL}: " UPASS; echo; }
[ -z "$UPASS" ] && { echo "senha vazia — abortando"; exit 1; }
T=PLATFORM_DATAFORALL_CUSTOMER_ADMIN
PW=$(grep '^MYSQL_ROOT_PASSWORD=' /opt/dataforall/deploy/.env | cut -d= -f2-)
HASH=$(docker exec dataforall-customer-admin python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('$UPASS'))" 2>/dev/null | tr -d '\r')
[ -z "$HASH" ] && { echo "FALHA ao gerar hash Argon2id"; exit 1; }
docker exec -i dataforall-tenant-mysql mysql -uroot -p"$PW" "$T" 2>&1 <<SQL | grep -viE 'insecure'
INSERT INTO accounts (org_name, email, email_domain, password_hash, status, email_verified_at, is_active, is_deleted, id_environment, created_at, updated_at)
VALUES ('DataForAll HML', '$EMAIL', SUBSTRING_INDEX('$EMAIL','@',-1), '$HASH', 'active_trial', NOW(), 1, 0, 1, NOW(), NOW())
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash), status='active_trial', email_verified_at=NOW(), is_active=1, is_deleted=0, updated_at=NOW();
SQL
echo "OK: account '$EMAIL' semeada em $T.accounts (login em platform.d4all.com.br /api/v1/auth/login)"
