#!/usr/bin/env bash
# Registra a rota /api/v1/partner/* -> dataforall-customer-admin no GATEWAY_MAPPING.
#
# O gateway resolve o serviço por `path_prefix` (extraído de /api/v1/{prefix}/...).
# Sem esta linha, /api/v1/partner/* volta 404 "No service registered for path" e o
# Console do Parceiro não carrega. Idempotente.
#
# Depois de rodar, reinicie o gateway para recarregar o registry (cacheado):
#   docker restart platform-api-gateway
set -euo pipefail

AM="${ADMIN_MYSQL_CONTAINER:-dataforall-admin-mysql}"

# SQL via env var para evitar inferno de aspas no docker exec.
mysql_exec() {
  docker exec -e SQL="$1" "$AM" \
    sh -c 'mysql -uroot -p"$(printenv MYSQL_ROOT_PASSWORD)" -N -e "$SQL"' 2>/dev/null \
    | grep -v "insecure" || true
}

EXISTS="$(mysql_exec "SELECT COUNT(*) FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE path_prefix='/partner';")"

if [ "${EXISTS:-0}" -gt 0 ]; then
  echo "rota /partner já registrada no GATEWAY_MAPPING — nada a fazer."
  exit 0
fi

mysql_exec "INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING
  (name_microservice, internal_url, version, path_prefix, strip_prefix, public_paths,
   health_path, timeout_seconds, retry_max_attempts, circuit_breaker_threshold,
   circuit_breaker_recovery_seconds, kind, tools_list_path, tools_call_path, created_at, updated_at)
  VALUES ('dataforall-customer-admin', 'http://dataforall-customer-admin:8000', 'v1',
          '/partner', 0, '[]', '/api/health/ready', 30, 3, 1, 5, 'rest',
          '/mcp/tools/list', '/mcp/tools/call', NOW(), NOW());"

echo "rota /partner -> dataforall-customer-admin registrada no GATEWAY_MAPPING."
echo "Reinicie o gateway p/ recarregar o registry: docker restart platform-api-gateway"
