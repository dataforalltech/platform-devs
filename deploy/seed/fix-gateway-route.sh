#!/usr/bin/env bash
# fix-gateway-route.sh <servico> [porta] — aponta a rota do gateway para o
# nome de container do servico (o bootstrap do gateway usa http://localhost:<porta>,
# que nao existe no compose). Ver bring-up-errors-and-fixes.md E4.
#
#   ./fix-gateway-route.sh platform-auth
#   ./fix-gateway-route.sh platform-admin 8000
set -uo pipefail
SVC="${1:?uso: fix-gateway-route.sh <servico> [porta]}"
PORT="${2:-8000}"
ENVF=/opt/dataforall/deploy/.env
PW=$(grep '^MYSQL_ROOT_PASSWORD=' "$ENVF" | cut -d= -f2-)

docker exec dataforall-admin-mysql mysql -uroot -p"$PW" -e \
  "UPDATE ADMIN_DATAFORALL.GATEWAY_MAPPING SET internal_url='http://${SVC}:${PORT}' WHERE name_microservice='${SVC}';" 2>/dev/null \
  && echo "rota ${SVC} -> http://${SVC}:${PORT}"
docker restart platform-api-gateway >/dev/null && echo "gateway reiniciado (rotas recarregadas)"
docker exec dataforall-admin-mysql mysql -uroot -p"$PW" -N -e \
  "SELECT name_microservice,internal_url FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice='${SVC}';" 2>/dev/null
